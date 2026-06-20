"""ui/documents_view.py — Modern searchable document table for DocuWise."""
from __future__ import annotations
import logging
from PyQt6.QtCore import Qt, QSortFilterProxyModel
from PyQt6.QtGui import QFont, QStandardItemModel, QStandardItem, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QLineEdit, QComboBox, QTableView, QHeaderView,
    QAbstractItemView, QSizePolicy, QSplitter,
)
from core.database import _connect, get_all_documents
from ui.file_actions import make_context_menu, open_document
from ui import styles as S

logger = logging.getLogger(__name__)

_COLUMNS = ["Filename", "Category", "Subject", "Status", "Importance", "Size", "Source"]
_COL_IDX = {n: i for i, n in enumerate(_COLUMNS)}

_STATUS_COLORS = {
    "embedded":   S.SUCCESS,
    "analyzed":   S.INFO,
    "extracted":  S.WARNING,
    "pending":    S.MUTED,
    "failed":     S.DANGER,
    "missing":    S.CARD_MISS,
    "image_only": S.CARD_IMGS,
}

_SOURCE_LABELS = {
    "nvidia":    "NVIDIA",
    "gemini":    "Gemini",
    "fallback":  "Heuristic",
    "cached":    "Cached",
}


class DocumentsView(QWidget):
    """Full-featured document table with search, filters, and detail panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder: str | None = None
        self._docs: list[dict] = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # Header
        header = QLabel("Documents")
        hf = QFont(); hf.setPointSize(22); hf.setBold(True)
        header.setFont(hf)
        header.setStyleSheet(f"color: {S.TEXT};")
        root.addWidget(header)

        # ── Toolbar ─────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)

        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Search documents...")
        self._search.setStyleSheet(S.search_box())
        self._search.setMinimumHeight(40)
        self._search.textChanged.connect(self._apply_filters)
        toolbar.addWidget(self._search, stretch=1)

        self._cat_combo = QComboBox()
        self._cat_combo.addItem("All Categories")
        self._cat_combo.setMinimumHeight(40)
        self._cat_combo.currentIndexChanged.connect(self._apply_filters)
        toolbar.addWidget(self._cat_combo)

        self._status_combo = QComboBox()
        self._status_combo.addItem("All Statuses")
        for s in ["embedded", "analyzed", "extracted", "pending", "failed", "missing", "image_only"]:
            self._status_combo.addItem(s.replace("_", " ").title(), s)
        self._status_combo.setMinimumHeight(40)
        self._status_combo.currentIndexChanged.connect(self._apply_filters)
        toolbar.addWidget(self._status_combo)

        self._count_lbl = QLabel()
        self._count_lbl.setStyleSheet(f"color: {S.MUTED}; font-size: 12px;")
        toolbar.addWidget(self._count_lbl)

        root.addLayout(toolbar)

        # ── Splitter: table + detail ────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {S.BORDER}; width: 1px; }}")

        # Table
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(_COLUMNS)

        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)  # search all columns

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(_COLUMNS)):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        self._table.doubleClicked.connect(self._on_double_click)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_ctx)
        self._table.selectionModel().currentChanged.connect(self._on_selection)

        splitter.addWidget(self._table)

        # Detail panel
        self._detail = _DetailPanel()
        splitter.addWidget(self._detail)
        splitter.setSizes([700, 340])

        root.addWidget(splitter, stretch=1)

    # ── Public API ──────────────────────────────────────────────────────────

    def set_folder(self, folder: str | None):
        self._folder = folder

    def refresh(self):
        like = _like(self._folder)
        try:
            conn = _connect()
            if like:
                rows = conn.execute(
                    "SELECT * FROM documents WHERE file_path LIKE ?"
                    " ORDER BY filename COLLATE NOCASE", (like,)
                ).fetchall()
                self._docs = [dict(r) for r in rows]
            else:
                self._docs = get_all_documents()
            conn.close()
        except Exception:
            self._docs = []

        logger.info("DocumentsView loaded %d documents (folder=%s)", len(self._docs), self._folder)
        self._populate()
        self._refresh_categories()
        self._update_count()

    # ── Internal ────────────────────────────────────────────────────────────

    def _populate(self):
        self._model.removeRows(0, self._model.rowCount())
        for doc in self._docs:
            row = self._make_row(doc)
            self._model.appendRow(row)

    def _make_row(self, doc: dict) -> list[QStandardItem]:
        filename = doc.get("filename") or ""
        category = doc.get("category") or "—"
        subject  = doc.get("subject") or "—"
        status   = doc.get("processing_status") or "—"
        score    = doc.get("importance_score")
        imp      = f"{max(1,min(10,int(score)))}/10" if score is not None else "—"
        size_kb  = doc.get("file_size_kb") or 0
        size_str = f"{size_kb/1024:.1f} MB" if size_kb >= 1024 else f"{size_kb:.0f} KB"
        source   = _SOURCE_LABELS.get(doc.get("analysis_source", ""), "—")

        items = [
            QStandardItem(filename),
            QStandardItem(category),
            QStandardItem(subject),
            QStandardItem(status.replace("_", " ").title()),
            QStandardItem(imp),
            QStandardItem(size_str),
            QStandardItem(source),
        ]

        # Color the status cell
        color = _STATUS_COLORS.get(status, S.MUTED)
        items[3].setForeground(QColor(color))

        # Store the full doc dict on the first item
        items[0].setData(doc, Qt.ItemDataRole.UserRole)

        for item in items:
            item.setEditable(False)

        return items

    def _refresh_categories(self):
        current = self._cat_combo.currentText()
        self._cat_combo.blockSignals(True)
        self._cat_combo.clear()
        self._cat_combo.addItem("All Categories")
        cats = sorted({d.get("category", "") for d in self._docs if d.get("category")})
        self._cat_combo.addItems(cats)
        idx = self._cat_combo.findText(current)
        if idx >= 0:
            self._cat_combo.setCurrentIndex(idx)
        self._cat_combo.blockSignals(False)

    def _apply_filters(self):
        text = self._search.text()
        self._proxy.setFilterFixedString(text)

        # Apply category and status filters by hiding rows
        cat = self._cat_combo.currentText()
        status_data = self._status_combo.currentData()

        for row_idx in range(self._model.rowCount()):
            source_idx = self._proxy.mapFromSource(self._model.index(row_idx, 0))
            doc_item = self._model.item(row_idx, 0)
            if not doc_item:
                continue
            doc = doc_item.data(Qt.ItemDataRole.UserRole)
            if not doc:
                continue

            show = True
            if cat != "All Categories" and doc.get("category") != cat:
                show = False
            if status_data and doc.get("processing_status") != status_data:
                show = False

            # Hiding is done through the proxy — but QSortFilterProxyModel doesn't
            # support multi-column filtering easily. So we re-hide via the table.
            proxy_row = source_idx.row()
            if proxy_row >= 0:
                self._table.setRowHidden(proxy_row, not show)

        self._update_count()

    def _update_count(self):
        visible = sum(1 for i in range(self._proxy.rowCount())
                      if not self._table.isRowHidden(i))
        total = len(self._docs)
        self._count_lbl.setText(f"{visible} of {total} documents")

    def _on_double_click(self, index):
        source = self._proxy.mapToSource(index)
        item = self._model.item(source.row(), 0)
        if item:
            doc = item.data(Qt.ItemDataRole.UserRole)
            if doc:
                open_document(doc.get("file_path", ""), self)

    def _on_ctx(self, pos):
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        source = self._proxy.mapToSource(index)
        item = self._model.item(source.row(), 0)
        if not item:
            return
        doc = item.data(Qt.ItemDataRole.UserRole)
        if doc:
            menu = make_context_menu(doc.get("file_path", ""), self)
            menu.exec(self._table.viewport().mapToGlobal(pos))

    def _on_selection(self, current, _previous):
        source = self._proxy.mapToSource(current)
        item = self._model.item(source.row(), 0)
        if item:
            doc = item.data(Qt.ItemDataRole.UserRole)
            self._detail.show_doc(doc)
        else:
            self._detail.clear()


class _DetailPanel(QFrame):
    """Right-side document detail panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(S.card())
        self.setMinimumWidth(300)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(20, 16, 20, 16)
        self._lay.setSpacing(12)

        self._title = QLabel("Select a document")
        tf = QFont(); tf.setPointSize(14); tf.setBold(True)
        self._title.setFont(tf)
        self._title.setWordWrap(True)
        self._title.setStyleSheet(f"color: {S.TEXT}; border: none;")
        self._lay.addWidget(self._title)

        self._content = QVBoxLayout()
        self._content.setSpacing(8)
        self._lay.addLayout(self._content)
        self._lay.addStretch()

    def clear(self):
        self._title.setText("Select a document")
        _clear_layout(self._content)

    def show_doc(self, doc: dict | None):
        _clear_layout(self._content)
        if not doc:
            self.clear()
            return

        self._title.setText(doc.get("filename", "Unknown"))

        fields = [
            ("Category",   doc.get("category")),
            ("Subject",    doc.get("subject")),
            ("Status",     (doc.get("processing_status") or "").replace("_", " ").title()),
            ("Importance", f"{int(doc['importance_score'])}/10" if doc.get("importance_score") else None),
            ("Source",     _SOURCE_LABELS.get(doc.get("analysis_source", ""), None)),
            ("Words",      str(doc.get("word_count")) if doc.get("word_count") else None),
            ("Size",       _format_size(doc.get("file_size_kb"))),
            ("MD5",        (doc.get("md5_hash") or "")[:16] + "…" if doc.get("md5_hash") else None),
        ]

        for label, value in fields:
            if not value:
                continue
            row = QHBoxLayout()
            row.setSpacing(8)
            k = QLabel(label)
            k.setStyleSheet(f"color: {S.MUTED}; font-size: 12px;")
            k.setFixedWidth(80)
            v = QLabel(str(value))
            v.setStyleSheet(f"color: {S.TEXT_SEC}; font-size: 12px;")
            v.setWordWrap(True)
            row.addWidget(k)
            row.addWidget(v, stretch=1)
            w = QWidget()
            w.setLayout(row)
            self._content.addWidget(w)

        # Summary
        summary = doc.get("summary")
        if summary and not summary.startswith("[ERROR]"):
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"color: {S.BORDER};")
            self._content.addWidget(sep)

            slbl = QLabel("Summary")
            slbl.setStyleSheet(f"color: {S.ACCENT}; font-weight: bold; font-size: 12px;")
            self._content.addWidget(slbl)

            stxt = QLabel(summary)
            stxt.setWordWrap(True)
            stxt.setStyleSheet(f"color: {S.TEXT_SEC}; font-size: 12px; line-height: 1.4;")
            self._content.addWidget(stxt)

        # Tags
        tags_raw = doc.get("tags_json")
        if tags_raw:
            import json
            try:
                tags = json.loads(tags_raw)
                if tags:
                    tag_row = QHBoxLayout()
                    tag_row.setSpacing(4)
                    for t in tags[:6]:
                        chip = QLabel(str(t))
                        chip.setStyleSheet(f"""
                            background: {S.ACCENT}22;
                            color: {S.ACCENT};
                            border-radius: 4px;
                            padding: 2px 8px;
                            font-size: 11px;
                        """)
                        tag_row.addWidget(chip)
                    tag_row.addStretch()
                    tw = QWidget()
                    tw.setLayout(tag_row)
                    self._content.addWidget(tw)
            except Exception:
                pass


# ── Helpers ──────────────────────────────────────────────────────────────────

def _like(folder: str | None) -> str | None:
    if not folder:
        return None
    return folder.rstrip("\\/") + "\\" + "%"

def _format_size(kb) -> str | None:
    if not kb:
        return None
    return f"{kb/1024:.1f} MB" if kb >= 1024 else f"{kb:.0f} KB"

def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()
        sub = item.layout()
        if sub:
            _clear_layout(sub)
