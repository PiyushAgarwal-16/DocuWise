"""
ui/main_window.py — Main application window for DocuWise.

New in this version:
  - Category distribution panel (Feature 5)
  - Duplicate storage-savings calculation (Feature 6)
  - Tooltips on stat cards (Feature 8)
"""

from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QPushButton, QProgressBar,
    QFileDialog, QGroupBox, QTreeWidget, QTreeWidgetItem,
    QStatusBar, QFrame, QSizePolicy,
    QMessageBox, QHeaderView, QScrollArea,
)

from core.database import _connect, init_db
from core.pipeline import run_full_scan
from ui.document_table import DocumentTableWidget
from ui.file_actions import make_context_menu, open_document


# ---------------------------------------------------------------------------
# Background scan worker
# ---------------------------------------------------------------------------

class _ScanWorker(QObject):
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, folder: str):
        super().__init__()
        self._folder = folder

    def run(self):
        try:
            self.finished.emit(run_full_scan(self._folder))
        except Exception as exc:              # noqa: BLE001
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Stat card
# ---------------------------------------------------------------------------

class _StatCard(QFrame):
    def __init__(self, label: str, value: str = "—",
                 color: str = "#2c3e50", tooltip: str = "", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if tooltip:
            self.setToolTip(tooltip)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        self._value_lbl = QLabel(value)
        vf = QFont(); vf.setPointSize(22); vf.setBold(True)
        self._value_lbl.setFont(vf)
        self._value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_lbl.setStyleSheet(f"color: {color};")

        self._label_lbl = QLabel(label)
        lf = QFont(); lf.setPointSize(8)
        self._label_lbl.setFont(lf)
        self._label_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label_lbl.setStyleSheet("color: #666;")

        layout.addWidget(self._value_lbl)
        layout.addWidget(self._label_lbl)

    def set_value(self, value: str | int):
        self._value_lbl.setText(str(value))


# ---------------------------------------------------------------------------
# Collapsible section
# ---------------------------------------------------------------------------

class _CollapsibleSection(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title_base = title
        self._expanded = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._toggle = QPushButton(f"▶  {title}")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(False)
        self._toggle.setStyleSheet(
            "QPushButton { text-align: left; padding: 6px 8px; font-weight: bold;"
            " background: #ecf0f1; border: 1px solid #bdc3c7; border-radius: 3px; }"
            " QPushButton:checked { background: #dfe6e9; }"
        )
        self._toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self._toggle)

        self._content = QWidget()
        self._content.setVisible(False)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._content)

    def _on_toggled(self, checked: bool):
        self._expanded = checked
        self._content.setVisible(checked)
        self._update_button_text()

    def _update_button_text(self):
        arrow = "▼" if self._expanded else "▶"
        self._toggle.setText(f"{arrow}  {self._title_base}")

    def set_title(self, title: str):
        self._title_base = title
        self._update_button_text()

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout


# ---------------------------------------------------------------------------
# Duplicates panel (Feature 6 — storage savings)
# ---------------------------------------------------------------------------

class _DuplicatesPanel(_CollapsibleSection):
    def __init__(self, parent=None):
        super().__init__("Duplicates  (0)", parent)

        self._savings_lbl = QLabel()
        self._savings_lbl.setStyleSheet("color: #c0392b; font-weight: bold; padding: 2px 0;")
        self._savings_lbl.setVisible(False)
        self.content_layout().addWidget(self._savings_lbl)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["File A", "File B", "Score", "Type"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setMinimumHeight(130)
        self._tree.setToolTip("Semantically or structurally similar document detected.")
        h = self._tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.content_layout().addWidget(self._tree)

        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

    def _on_double_click(self, item: QTreeWidgetItem, col: int):
        fp = item.data(col, Qt.ItemDataRole.UserRole) or ""
        if fp:
            open_document(fp, self)

    def _on_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return
        fp = item.data(1, Qt.ItemDataRole.UserRole) or ""
        if fp:
            make_context_menu(fp, self).exec(self._tree.viewport().mapToGlobal(pos))

    def refresh(self):
        self._tree.clear()
        try:
            conn = _connect()
            rows = conn.execute("""
                SELECT
                    d1.filename        AS file_a,
                    d1.file_path       AS path_a,
                    d2.filename        AS file_b,
                    d2.file_path       AS path_b,
                    d2.file_size_kb    AS size_b,
                    dr.similarity_score,
                    dr.relationship_type
                FROM document_relationships dr
                JOIN documents d1 ON d1.id = dr.source_document_id
                JOIN documents d2 ON d2.id = dr.target_document_id
                WHERE dr.relationship_type IN ('duplicate', 'similar')
                ORDER BY dr.similarity_score DESC
            """).fetchall()
            conn.close()
        except Exception:
            rows = []

        total_savings_kb = 0.0
        for row in rows:
            item = QTreeWidgetItem([row[0], row[2], f"{row[5]:.3f}", row[6]])
            item.setData(0, Qt.ItemDataRole.UserRole, row[1])
            item.setData(1, Qt.ItemDataRole.UserRole, row[3])
            if row[6] == "duplicate":
                for col in range(4):
                    item.setForeground(col, QColor("#c0392b"))
                if row[4]:
                    total_savings_kb += row[4]
            self._tree.addTopLevelItem(item)

        count = self._tree.topLevelItemCount()
        self.set_title(f"Duplicates  ({count})")

        if total_savings_kb > 0:
            kb = total_savings_kb
            self._savings_lbl.setText(
                f"Potential space savings: {kb / 1024:.1f} MB" if kb >= 1024
                else f"Potential space savings: {kb:.0f} KB"
            )
            self._savings_lbl.setVisible(True)
        else:
            self._savings_lbl.setVisible(False)


# ---------------------------------------------------------------------------
# Image PDF panel
# ---------------------------------------------------------------------------

class _ImagePDFPanel(_CollapsibleSection):
    def __init__(self, parent=None):
        super().__init__("Image-only PDFs  (0)", parent)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Filename", "Note"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setMinimumHeight(90)
        self._tree.setToolTip("Text extraction unavailable. OCR required.")
        h = self._tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.content_layout().addWidget(self._tree)

        self._tree.itemDoubleClicked.connect(
            lambda item, _: open_document(item.data(0, Qt.ItemDataRole.UserRole) or "", self)
        )
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

    def _on_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return
        fp = item.data(0, Qt.ItemDataRole.UserRole) or ""
        if fp:
            make_context_menu(fp, self).exec(self._tree.viewport().mapToGlobal(pos))

    def refresh(self):
        self._tree.clear()
        try:
            conn = _connect()
            rows = conn.execute("""
                SELECT filename, file_path FROM documents
                WHERE processing_status = 'image_only'
                ORDER BY filename COLLATE NOCASE
            """).fetchall()
            conn.close()
        except Exception:
            rows = []
        for row in rows:
            item = QTreeWidgetItem([row[0], "Image-based PDF — OCR not supported"])
            item.setData(0, Qt.ItemDataRole.UserRole, row[1])
            self._tree.addTopLevelItem(item)
        self.set_title(f"Image-only PDFs  ({self._tree.topLevelItemCount()})")


# ---------------------------------------------------------------------------
# Missing files panel (Task 4, 5, 6)
# ---------------------------------------------------------------------------

class _MissingPanel(_CollapsibleSection):
    """Files that exist in the database but are no longer on disk."""

    def __init__(self, parent=None):
        super().__init__("Missing Files  (0)", parent)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Filename", "Original Path", "Status"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setMinimumHeight(90)
        self._tree.setToolTip("File was deleted from disk but still recorded in the database.")
        h = self._tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.content_layout().addWidget(self._tree)

        # Double-click shows the "file not found" warning via shared helper
        self._tree.itemDoubleClicked.connect(
            lambda item, _: open_document(item.data(0, Qt.ItemDataRole.UserRole) or "", self)
        )
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

    def _on_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return
        fp = item.data(0, Qt.ItemDataRole.UserRole) or ""
        if fp:
            make_context_menu(fp, self).exec(self._tree.viewport().mapToGlobal(pos))

    def refresh(self):
        self._tree.clear()
        try:
            conn = _connect()
            rows = conn.execute("""
                SELECT filename, file_path FROM documents
                WHERE processing_status = 'missing'
                ORDER BY filename COLLATE NOCASE
            """).fetchall()
            conn.close()
        except Exception:
            rows = []

        for row in rows:
            item = QTreeWidgetItem([row[0], row[1], "Missing from disk"])
            item.setData(0, Qt.ItemDataRole.UserRole, row[1])
            item.setForeground(0, QColor("#c0392b"))
            item.setForeground(2, QColor("#c0392b"))
            self._tree.addTopLevelItem(item)

        self.set_title(f"Missing Files  ({self._tree.topLevelItemCount()})")


# ---------------------------------------------------------------------------
# Category distribution panel (Feature 5)
# ---------------------------------------------------------------------------

class _CategoryPanel(_CollapsibleSection):
    """Horizontal QProgressBar bars showing category distribution."""

    _CATEGORY_COLORS = {
        "Academic":     "#3498db",
        "Technical":    "#2ecc71",
        "Personal":     "#e74c3c",
        "Finance":      "#f39c12",
        "Legal":        "#9b59b6",
        "Work":         "#1abc9c",
        "Medical":      "#e91e63",
        "Miscellaneous":"#95a5a6",
    }

    def __init__(self, parent=None):
        super().__init__("Category Distribution", parent)
        self._bars: dict[str, tuple[QProgressBar, QLabel]] = {}
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(2, 2, 2, 2)
        self._container_layout.setSpacing(4)
        self.content_layout().addWidget(self._container)

    def refresh(self):
        # Clear existing bars
        while self._container_layout.count():
            item = self._container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._bars.clear()

        try:
            conn = _connect()
            rows = conn.execute("""
                SELECT category, COUNT(*) AS cnt
                FROM documents
                WHERE category IS NOT NULL
                GROUP BY category
                ORDER BY cnt DESC
            """).fetchall()
            conn.close()
        except Exception:
            rows = []

        if not rows:
            self._container_layout.addWidget(QLabel("No analyzed documents yet."))
            self.set_title("Category Distribution")
            return

        max_count = max(r[1] for r in rows) or 1

        for cat, cnt in rows:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            cat_lbl = QLabel(cat)
            cat_lbl.setFixedWidth(90)
            cat_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            bar = QProgressBar()
            bar.setRange(0, max_count)
            bar.setValue(cnt)
            bar.setTextVisible(False)
            bar.setMaximumHeight(14)
            color = self._CATEGORY_COLORS.get(cat, "#7f8c8d")
            bar.setStyleSheet(
                f"QProgressBar {{ border: 1px solid #ccc; border-radius: 3px; }}"
                f"QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
            )

            cnt_lbl = QLabel(str(cnt))
            cnt_lbl.setFixedWidth(28)
            cnt_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            cnt_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")

            row_layout.addWidget(cat_lbl)
            row_layout.addWidget(bar, stretch=1)
            row_layout.addWidget(cnt_lbl)
            self._container_layout.addWidget(row_widget)

        total = sum(r[1] for r in rows)
        self.set_title(f"Category Distribution  ({total} docs)")


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._folder: Optional[str] = None
        self._scan_thread: Optional[QThread] = None
        self._scan_worker: Optional[_ScanWorker] = None
        init_db()
        self._build_ui()
        self._refresh_stats()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle("DocuWise — Intelligent Document Manager")
        self.resize(1400, 900)
        self.setMinimumSize(900, 600)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._build_toolbar())
        root.addLayout(self._build_stats_row())

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setMaximumHeight(6)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        # Main content area
        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.setChildrenCollapsible(False)

        self._doc_table = DocumentTableWidget()
        h_splitter.addWidget(self._doc_table)

        # Right panel — scrollable stack of collapsible sections
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setMinimumWidth(320)
        right_scroll.setMaximumWidth(400)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self._dup_panel    = _DuplicatesPanel()
        self._img_panel    = _ImagePDFPanel()
        self._missing_panel = _MissingPanel()
        self._cat_panel    = _CategoryPanel()

        right_layout.addWidget(self._dup_panel)
        right_layout.addWidget(self._img_panel)
        right_layout.addWidget(self._missing_panel)
        right_layout.addWidget(self._cat_panel)
        right_layout.addStretch()

        right_scroll.setWidget(right_widget)
        h_splitter.addWidget(right_scroll)
        h_splitter.setSizes([1020, 360])

        root.addWidget(h_splitter, stretch=1)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready. Browse a folder to begin scanning.")

        self._dup_panel.refresh()
        self._img_panel.refresh()
        self._missing_panel.refresh()
        self._cat_panel.refresh()

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        title = QLabel("DocuWise")
        tf = QFont(); tf.setPointSize(14); tf.setBold(True)
        title.setFont(tf)
        layout.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        self._folder_label = QLabel("No folder selected")
        self._folder_label.setStyleSheet("color: #555; font-style: italic;")
        self._folder_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._folder_label, stretch=1)

        self._btn_browse = QPushButton("📂  Browse Folder")
        self._btn_browse.setMinimumHeight(34)
        self._btn_browse.setToolTip("Select a folder to scan for documents")
        self._btn_browse.clicked.connect(self._on_browse)

        self._btn_scan = QPushButton("▶  Scan Documents")
        self._btn_scan.setMinimumHeight(34)
        self._btn_scan.setEnabled(False)
        self._btn_scan.setToolTip("Run the full DocuWise intelligence pipeline on the selected folder")
        self._btn_scan.clicked.connect(self._on_scan)

        self._btn_refresh = QPushButton("⟳  Refresh")
        self._btn_refresh.setMinimumHeight(34)
        self._btn_refresh.setToolTip("Reload data from the database without re-scanning")
        self._btn_refresh.clicked.connect(self._on_refresh)

        layout.addWidget(self._btn_browse)
        layout.addWidget(self._btn_scan)
        layout.addWidget(self._btn_refresh)
        return bar

    def _build_stats_row(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)

        self._card_total      = _StatCard("Total Documents",  "—", "#2c3e50",
                                          "All files discovered by the scanner")
        self._card_embedded   = _StatCard("Embedded",         "—", "#27ae60",
                                          "Documents with AI embeddings — ready for duplicate detection")
        self._card_image      = _StatCard("Image PDFs",       "—", "#8e44ad",
                                          "Image-based PDFs. Text extraction unavailable. OCR required.")
        self._card_duplicates = _StatCard("Duplicates",       "—", "#e74c3c",
                                          "Semantically or structurally similar document pairs detected")
        self._card_missing    = _StatCard("Missing",          "—", "#d35400",
                                          "Files removed from disk but still recorded in the database")
        self._card_failed     = _StatCard("Failed",           "—", "#c0392b",
                                          "Documents that failed processing — check logs for details")

        for card in [self._card_total, self._card_embedded, self._card_image,
                     self._card_duplicates, self._card_missing, self._card_failed]:
            layout.addWidget(card)
        return layout

    # ── Stats ─────────────────────────────────────────────────────────────────

    def _refresh_stats(self):
        try:
            conn = _connect()
            row = conn.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN processing_status='embedded'   THEN 1 ELSE 0 END) AS embedded,
                    SUM(CASE WHEN processing_status='image_only' THEN 1 ELSE 0 END) AS image_only,
                    SUM(CASE WHEN processing_status='failed'     THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN processing_status='missing'    THEN 1 ELSE 0 END) AS missing
                FROM documents
            """).fetchone()
            dup_row = conn.execute("""
                SELECT COUNT(*) FROM document_relationships
                WHERE relationship_type = 'duplicate'
            """).fetchone()
            conn.close()

            self._card_total.set_value(row[0] or 0)
            self._card_embedded.set_value(row[1] or 0)
            self._card_image.set_value(row[2] or 0)
            self._card_duplicates.set_value(dup_row[0] or 0)
            self._card_missing.set_value(row[4] or 0)
            self._card_failed.set_value(row[3] or 0)
        except Exception as exc:
            self._status_bar.showMessage(f"Stats error: {exc}")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder to Scan",
            self._folder or os.path.expanduser("~"),
        )
        if folder:
            self._folder = folder
            self._folder_label.setText(folder)
            self._folder_label.setStyleSheet("color: #333; font-style: normal;")
            self._btn_scan.setEnabled(True)
            self._status_bar.showMessage(f"Folder selected: {folder}")

    def _on_scan(self):
        if not self._folder or (self._scan_thread and self._scan_thread.isRunning()):
            return
        self._set_scanning(True)
        self._status_bar.showMessage(f"Scanning '{self._folder}'…")

        self._scan_thread = QThread()
        self._scan_worker = _ScanWorker(self._folder)
        self._scan_worker.moveToThread(self._scan_thread)

        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.error.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(lambda: self._set_scanning(False))

        self._scan_thread.start()

    def _on_refresh(self):
        self._doc_table.refresh()
        self._dup_panel.refresh()
        self._img_panel.refresh()
        self._missing_panel.refresh()
        self._cat_panel.refresh()
        self._refresh_stats()
        self._status_bar.showMessage("Refreshed.")

    # ── Scan callbacks ────────────────────────────────────────────────────────

    def _on_scan_finished(self, result: dict):
        scan    = result.get("scan", {})
        pipe    = result.get("pipeline", {})
        rescue  = result.get("rescue", {})
        dups    = result.get("duplicates", {})
        missing = result.get("missing", 0)
        rescued = rescue.get("case_a_fixed", 0) + rescue.get("case_b_embedded", 0)

        parts = [f"{scan.get('total_files', 0)} files",
                 f"{pipe.get('processed', 0)} processed"]
        if rescued:  parts.append(f"{rescued} rescued")
        if missing:  parts.append(f"{missing} missing")
        parts.append(f"{dups.get('duplicates_found', 0)} duplicates")
        if pipe.get("failed", 0): parts.append(f"{pipe['failed']} failed")

        self._status_bar.showMessage("Scan complete — " + " | ".join(parts))
        self._on_refresh()


    def _on_scan_error(self, error_msg: str):
        QMessageBox.critical(self, "Scan Error", f"The scan failed:\n\n{error_msg}")
        self._status_bar.showMessage("Scan failed.")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_scanning(self, scanning: bool):
        self._btn_scan.setEnabled(not scanning and self._folder is not None)
        self._btn_browse.setEnabled(not scanning)
        self._btn_refresh.setEnabled(not scanning)
        self._progress.setVisible(scanning)

    def closeEvent(self, event):
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.quit()
            self._scan_thread.wait(3000)
        event.accept()
