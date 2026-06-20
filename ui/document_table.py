"""
ui/document_table.py — Document list, search/filter, and detail panel for DocuWise.

Features:
  - Sortable, searchable, filterable QTableView
  - Importance mini-bar delegate (colour-coded 1-10)
  - Double-click → open file with system default app    (Feature 1)
  - Right-click context menu: Open File / Open Folder   (Feature 2)
  - Importance QProgressBar in detail panel             (Feature 3)
  - Analysis-source coloured badge in detail panel      (Feature 4)
  - File-exists guard before opening                    (Feature 7)
  - Tooltips on key UI elements                         (Feature 8)
"""

from __future__ import annotations

import json
from typing import Optional

from PyQt6.QtCore import Qt, QSortFilterProxyModel, QRect, QSize
from PyQt6.QtGui import (
    QStandardItemModel, QStandardItem, QColor, QFont,
    QPainter, QAction,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTableView, QLineEdit, QComboBox, QLabel,
    QGroupBox, QFormLayout, QTextEdit, QFrame,
    QAbstractItemView, QSizePolicy, QScrollArea,
    QProgressBar, QMenu, QMessageBox, QStyledItemDelegate,
    QApplication, QStyle,
)

from core.database import get_all_documents, _connect
from ui.file_actions import open_document, open_containing_folder, make_context_menu


# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------
_COLUMNS = ["Filename", "Category", "Subject", "Importance", "Status"]
_COL_FILENAME   = 0
_COL_CATEGORY   = 1
_COL_SUBJECT    = 2
_COL_IMPORTANCE = 3
_COL_STATUS     = 4

_ROLE_FILE_PATH  = Qt.ItemDataRole.UserRole
_ROLE_IMP_INT    = Qt.ItemDataRole.UserRole + 1   # raw importance int for delegate

_STATUS_COLORS = {
    "embedded":   "#27ae60",
    "analyzed":   "#2980b9",
    "extracted":  "#f39c12",
    "pending":    "#7f8c8d",
    "failed":     "#e74c3c",
    "image_only": "#8e44ad",
}

_SOURCE_COLORS = {
    "nvidia":   ("#1a6b3a", "#d5f5e3"),   # dark green text, light green bg
    "gemini":   ("#1a5276", "#d6eaf8"),   # dark blue text, light blue bg
    "fallback": ("#7d6608", "#fef9e7"),   # amber text, cream bg
    "cached":   ("#4a235a", "#f5eef8"),   # purple text, light purple bg
}


def _importance_color(value: int) -> str:
    if value <= 3:
        return "#e74c3c"
    if value <= 6:
        return "#f39c12"
    return "#27ae60"



# ---------------------------------------------------------------------------
# Importance mini-bar delegate (Feature 3 — table column)
# ---------------------------------------------------------------------------

class _ImportanceDelegate(QStyledItemDelegate):
    """Paints a small coloured progress bar + 'N/10' text in the Importance column."""

    def paint(self, painter: QPainter, option, index):
        value = index.data(_ROLE_IMP_INT)
        if value is None:
            super().paint(painter, option, index)
            return

        painter.save()

        is_sel = bool(option.state & QStyle.StateFlag.State_Selected)
        if is_sel:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            painter.fillRect(option.rect, option.palette.base())

        r = option.rect
        bar_h = 5
        pad   = 4
        bar_y = r.bottom() - bar_h - 3

        if not is_sel:
            # Track
            painter.fillRect(QRect(r.x() + pad, bar_y, r.width() - 2 * pad, bar_h),
                             QColor("#dfe6e9"))
            # Fill
            fill_w = int((r.width() - 2 * pad) * value / 10)
            painter.fillRect(QRect(r.x() + pad, bar_y, fill_w, bar_h),
                             QColor(_importance_color(value)))

        # Text
        label = f"{value}/10"
        text_rect = QRect(r.x(), r.y(), r.width(), r.height() - bar_h - 6)
        pen_color = (option.palette.highlightedText().color() if is_sel
                     else QColor(_importance_color(value)))
        painter.setPen(pen_color)
        bold = QFont(painter.font())
        bold.setBold(True)
        painter.setFont(bold)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(80, 38)


# ---------------------------------------------------------------------------
# Sortable proxy model
# ---------------------------------------------------------------------------

class _FilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._category_filter = ""
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(-1)

    def set_category_filter(self, category: str):
        self._category_filter = category
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        model = self.sourceModel()
        if self._category_filter:
            cat_item = model.item(source_row, _COL_CATEGORY)
            if (cat_item.text() if cat_item else "") != self._category_filter:
                return False
        search = self.filterRegularExpression().pattern()
        if not search:
            return True
        for col in range(model.columnCount()):
            item = model.item(source_row, col)
            if item and search.lower() in item.text().lower():
                return True
        return False

    def lessThan(self, left, right) -> bool:
        # Numeric sort for importance column
        if left.column() == _COL_IMPORTANCE:
            lv = left.data(_ROLE_IMP_INT) or 0
            rv = right.data(_ROLE_IMP_INT) or 0
            return lv < rv
        return super().lessThan(left, right)


# ---------------------------------------------------------------------------
# Detail panel (Features 3, 4, 8)
# ---------------------------------------------------------------------------

class DocumentDetailPanel(QWidget):
    """Right-hand panel showing full details for the selected document."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Document Details")
        tf = QFont(); tf.setPointSize(11); tf.setBold(True)
        title.setFont(tf)
        layout.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        self._form = QFormLayout(container)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._form.setSpacing(8)
        self._form.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(container)
        layout.addWidget(scroll)

        def lbl(text="—") -> QLabel:
            l = QLabel(text)
            l.setWordWrap(True)
            l.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            return l

        self._lbl_filename   = lbl()
        self._lbl_status     = lbl()
        self._lbl_category   = lbl()
        self._lbl_subject    = lbl()
        self._lbl_word_count = lbl()
        self._lbl_file_size  = lbl()
        self._lbl_tags       = lbl()
        self._lbl_deletion   = lbl()
        self._lbl_del_reason = lbl()

        # Importance: QProgressBar (Feature 3)
        self._imp_bar = QProgressBar()
        self._imp_bar.setRange(1, 10)
        self._imp_bar.setValue(1)
        self._imp_bar.setFormat("%v / 10")
        self._imp_bar.setMaximumHeight(22)
        self._imp_bar.setToolTip("AI-estimated importance score (1 = low, 10 = critical)")

        # Analysis source badge (Feature 4)
        self._lbl_source = QLabel("—")
        self._lbl_source.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_source.setToolTip("Model confidence in classification")

        self._txt_summary = QTextEdit()
        self._txt_summary.setReadOnly(True)
        self._txt_summary.setMaximumHeight(110)
        self._txt_summary.setPlaceholderText("No summary available.")

        self._form.addRow("Filename:",      self._lbl_filename)
        self._form.addRow("Status:",        self._lbl_status)
        self._form.addRow("Category:",      self._lbl_category)
        self._form.addRow("Subject:",       self._lbl_subject)
        self._form.addRow("Importance:",    self._imp_bar)
        self._form.addRow("Analysis:",      self._lbl_source)
        self._form.addRow("Words:",         self._lbl_word_count)
        self._form.addRow("Size:",          self._lbl_file_size)
        self._form.addRow("Tags:",          self._lbl_tags)
        self._form.addRow("Delete?",        self._lbl_deletion)
        self._form.addRow("Delete reason:", self._lbl_del_reason)
        self._form.addRow("Summary:",       self._txt_summary)

        self.clear()

    def clear(self):
        self._lbl_filename.setText("—")
        self._lbl_status.setText("—"); self._lbl_status.setStyleSheet("")
        self._lbl_category.setText("—")
        self._lbl_subject.setText("—")
        self._imp_bar.setValue(1)
        self._imp_bar.setStyleSheet("")
        self._imp_bar.setFormat("—")
        self._lbl_source.setText("—"); self._lbl_source.setStyleSheet("")
        self._lbl_word_count.setText("—")
        self._lbl_file_size.setText("—")
        self._lbl_tags.setText("—")
        self._lbl_deletion.setText("—"); self._lbl_deletion.setStyleSheet("")
        self._lbl_del_reason.setText("—")
        self._txt_summary.clear()

    def load(self, doc: dict):
        self.clear()
        if not doc:
            return

        self._lbl_filename.setText(doc.get("filename") or "—")

        status = doc.get("processing_status") or "—"
        self._lbl_status.setText(status)
        sc = _STATUS_COLORS.get(status)
        if sc:
            self._lbl_status.setStyleSheet(f"color: {sc}; font-weight: bold;")

        self._lbl_category.setText(doc.get("category") or "—")
        self._lbl_subject.setText(doc.get("subject") or "—")

        # Importance progress bar (Feature 3)
        score = doc.get("importance_score")
        if score is not None:
            v = max(1, min(10, int(score)))
            self._imp_bar.setValue(v)
            self._imp_bar.setFormat(f"{v} / 10")
            color = _importance_color(v)
            self._imp_bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {color}; }}"
            )
        else:
            self._imp_bar.setValue(1)
            self._imp_bar.setFormat("—")

        # Analysis source badge (Feature 4)
        source = doc.get("analysis_source") or ""
        if source:
            fg, bg = _SOURCE_COLORS.get(source.lower(), ("#333", "#eee"))
            self._lbl_source.setText(f"  [{source.upper()}]  ")
            self._lbl_source.setStyleSheet(
                f"color: {fg}; background: {bg}; border-radius: 4px;"
                f" padding: 2px 6px; font-weight: bold; font-size: 9pt;"
            )
        else:
            self._lbl_source.setText("—")
            self._lbl_source.setStyleSheet("")

        wc = doc.get("word_count")
        self._lbl_word_count.setText(f"{wc:,}" if wc else "—")
        kb = doc.get("file_size_kb")
        self._lbl_file_size.setText(f"{kb:.1f} KB" if kb else "—")

        tags_raw = doc.get("tags_json")
        if tags_raw:
            try:
                tags = json.loads(tags_raw)
                self._lbl_tags.setText(", ".join(tags) if tags else "—")
            except Exception:
                self._lbl_tags.setText("—")

        is_del = bool(doc.get("deletion_candidate"))
        self._lbl_deletion.setText("⚠ Yes" if is_del else "No")
        self._lbl_deletion.setStyleSheet(
            "color: #e74c3c; font-weight: bold;" if is_del else "color: #27ae60;"
        )
        self._lbl_del_reason.setText(doc.get("deletion_reason") or "—")
        self._txt_summary.setPlainText(doc.get("summary") or "")


# ---------------------------------------------------------------------------
# Main document table widget (Features 1, 2, 8)
# ---------------------------------------------------------------------------

class DocumentTableWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._docs: list[dict] = []
        self._folder_filter: str | None = None
        self._model = QStandardItemModel(0, len(_COLUMNS), self)
        self._model.setHorizontalHeaderLabels(_COLUMNS)
        self._proxy = _FilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self._build_ui()
        self.refresh()

    def set_folder_filter(self, folder: str | None):
        """Restrict the table to documents inside *folder*."""
        self._folder_filter = folder
        self.refresh()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # Search / filter toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("  🔍  Search filename, subject, category…")
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumHeight(30)
        self._search.textChanged.connect(self._on_search_changed)

        self._cat_filter = QComboBox()
        self._cat_filter.setMinimumHeight(30)
        self._cat_filter.setMinimumWidth(160)
        self._cat_filter.addItem("All Categories")
        self._cat_filter.currentTextChanged.connect(self._on_category_changed)

        self._count_label = QLabel("0 documents")
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        toolbar.addWidget(QLabel("Filter:"))
        toolbar.addWidget(self._search, stretch=3)
        toolbar.addWidget(self._cat_filter)
        toolbar.addWidget(self._count_label)
        outer.addLayout(toolbar)

        # Table + detail splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)

        # Importance delegate (Feature 3)
        self._imp_delegate = _ImportanceDelegate(self._table)
        self._table.setItemDelegateForColumn(_COL_IMPORTANCE, self._imp_delegate)

        # Column widths
        self._table.setColumnWidth(_COL_FILENAME,   260)
        self._table.setColumnWidth(_COL_CATEGORY,   110)
        self._table.setColumnWidth(_COL_SUBJECT,    220)
        self._table.setColumnWidth(_COL_IMPORTANCE,  80)
        self._table.setColumnWidth(_COL_STATUS,      90)
        self._table.verticalHeader().setDefaultSectionSize(38)

        # Signals
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._table.sortByColumn(_COL_FILENAME, Qt.SortOrder.AscendingOrder)
        self._table.doubleClicked.connect(self._on_double_click)          # Feature 1

        # Context menu (Feature 2)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)

        # Tooltips (Feature 8)
        self._table.setToolTip("Double-click to open • Right-click for more options")

        splitter.addWidget(self._table)

        detail_box = QGroupBox("Details")
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(8, 8, 8, 8)
        self._detail = DocumentDetailPanel()
        detail_layout.addWidget(self._detail)
        splitter.addWidget(detail_box)

        splitter.setSizes([680, 340])
        outer.addWidget(splitter, stretch=1)

    # ── Data ─────────────────────────────────────────────────────────────────

    def refresh(self):
        if self._folder_filter:
            like = self._folder_filter.rstrip("\\/") + "\\" + "%"
            try:
                conn = _connect()
                rows = conn.execute(
                    "SELECT * FROM documents WHERE file_path LIKE ?"
                    " ORDER BY filename COLLATE NOCASE",
                    (like,),
                ).fetchall()
                conn.close()
                self._docs = [dict(r) for r in rows]
            except Exception:
                self._docs = []
        else:
            self._docs = get_all_documents()
        self._populate_table()
        self._refresh_category_dropdown()
        self._update_count_label()

    def _populate_table(self):
        self._model.removeRows(0, self._model.rowCount())
        for doc in self._docs:
            filename   = doc.get("filename") or ""
            category   = doc.get("category") or "—"
            subject    = doc.get("subject") or "—"
            score      = doc.get("importance_score")
            imp_int    = max(1, min(10, int(score))) if score is not None else None
            imp_text   = f"{imp_int}/10" if imp_int is not None else "—"
            status     = doc.get("processing_status") or "—"

            items = [
                QStandardItem(filename),
                QStandardItem(category),
                QStandardItem(subject),
                QStandardItem(imp_text),   # text shown by non-delegate fallback
                QStandardItem(status),
            ]

            # Importance: store raw int for delegate + numeric sort
            items[_COL_IMPORTANCE].setData(imp_int, _ROLE_IMP_INT)

            # Status colour
            sc = _STATUS_COLORS.get(status)
            if sc:
                items[_COL_STATUS].setForeground(QColor(sc))
                items[_COL_STATUS].setFont(_bold_font())

            # Deletion highlight
            if doc.get("deletion_candidate"):
                items[_COL_FILENAME].setBackground(QColor("#ffeaea"))

            for item in items:
                item.setEditable(False)
            items[_COL_FILENAME].setData(doc.get("file_path", ""), _ROLE_FILE_PATH)

            self._model.appendRow(items)

    def _refresh_category_dropdown(self):
        categories = sorted({d.get("category") or "" for d in self._docs if d.get("category")})
        current = self._cat_filter.currentText()
        self._cat_filter.blockSignals(True)
        self._cat_filter.clear()
        self._cat_filter.addItem("All Categories")
        for cat in categories:
            self._cat_filter.addItem(cat)
        idx = self._cat_filter.findText(current)
        self._cat_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self._cat_filter.blockSignals(False)

    def _update_count_label(self):
        visible, total = self._proxy.rowCount(), self._model.rowCount()
        self._count_label.setText(
            f"{total} documents" if visible == total else f"{visible} of {total} documents"
        )

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_search_changed(self, text: str):
        self._proxy.setFilterFixedString(text)
        self._update_count_label()

    def _on_category_changed(self, text: str):
        self._proxy.set_category_filter("" if text == "All Categories" else text)
        self._update_count_label()

    def _on_selection_changed(self, selected, _deselected):
        indexes = selected.indexes()
        if not indexes:
            self._detail.clear()
            return
        file_path = self._file_path_from_proxy_row(indexes[0].row())
        self._detail.load(_load_doc_by_path(file_path) or {} if file_path else {})

    def _on_double_click(self, index):
        """Feature 1 — open file with system default app."""
        file_path = self._file_path_from_proxy_row(index.row())
        if file_path:
            open_document(file_path, self)

    def _on_context_menu(self, pos):
        """Feature 2 — right-click context menu."""
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        file_path = self._file_path_from_proxy_row(index.row())
        if not file_path:
            return
        menu = make_context_menu(file_path, self)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _file_path_from_proxy_row(self, proxy_row: int) -> Optional[str]:
        source_index = self._proxy.mapToSource(self._proxy.index(proxy_row, 0))
        item = self._model.item(source_index.row(), _COL_FILENAME)
        return item.data(_ROLE_FILE_PATH) if item else None


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _bold_font() -> QFont:
    f = QFont()
    f.setBold(True)
    return f


def _load_doc_by_path(file_path: str) -> Optional[dict]:
    try:
        conn = _connect()
        with conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE file_path = ? LIMIT 1",
                (file_path,),
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None
