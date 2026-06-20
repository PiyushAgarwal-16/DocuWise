"""ui/main_window.py — Sidebar-based main window for DocuWise."""
from __future__ import annotations
import logging
import os
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QSize
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QLabel, QPushButton, QStatusBar,
    QFrame, QMessageBox, QSizePolicy, QFileDialog,
    QSpacerItem,
)

from core.database import init_db
from core.pipeline import run_full_scan
from ui.dashboard import Dashboard
from ui.documents_view import DocumentsView
from ui.duplicates_view import DuplicatesView
from ui.image_pdfs_view import ImagePdfsView
from ui.cleanup_view import CleanupView
from ui.scan_overlay import ScanOverlay
from ui import styles as S

logger = logging.getLogger(__name__)

# Page indices
_DASHBOARD   = 0
_DOCUMENTS   = 1
_DUPLICATES  = 2
_IMAGE_PDFS  = 3
_CLEANUP     = 4
_SCAN        = 5


# ── Background worker ───────────────────────────────────────────────────────

class _ScanWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, folder: str):
        super().__init__()
        self._folder = folder

    def run(self):
        try:
            result = run_full_scan(
                self._folder,
                progress_callback=lambda c, t, f: self.progress.emit(c, t, f),
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


# ── Sidebar ─────────────────────────────────────────────────────────────────

class _SidebarButton(QPushButton):
    """A single navigation item in the sidebar."""

    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(f"  {icon}   {label}", parent)
        self.setCheckable(True)
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {S.MUTED};
                border: none;
                border-radius: 10px;
                text-align: left;
                padding-left: 16px;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background: {S.SURFACE};
                color: {S.TEXT};
            }}
            QPushButton:checked {{
                background: {S.ACCENT}22;
                color: {S.ACCENT};
                font-weight: bold;
            }}
        """)


class _Sidebar(QFrame):
    """Left navigation sidebar with folder selector."""

    page_changed    = pyqtSignal(int)
    scan_requested  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setStyleSheet(f"""
            QFrame {{
                background: {S.PANEL};
                border-right: 1px solid {S.BORDER};
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 16, 12, 16)
        lay.setSpacing(4)

        # Logo / Title
        title = QLabel("DocuWise")
        tf = QFont(); tf.setPointSize(16); tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color: {S.TEXT}; padding: 8px 8px 4px 8px; border: none;")
        lay.addWidget(title)

        subtitle = QLabel("Document Intelligence")
        subtitle.setStyleSheet(f"color: {S.MUTED_DIM}; font-size: 10px; padding: 0 8px 12px 8px; border: none;")
        lay.addWidget(subtitle)

        # Navigation buttons
        self._buttons: list[_SidebarButton] = []
        nav_items = [
            ("📊", "Dashboard"),
            ("📄", "Documents"),
            ("🔁", "Duplicates"),
            ("🖼", "Image PDFs"),
            ("🧹", "Cleanup"),
        ]
        for i, (icon, label) in enumerate(nav_items):
            btn = _SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, idx=i: self._on_nav(idx))
            self._buttons.append(btn)
            lay.addWidget(btn)

        lay.addStretch()

        # Scan button
        self._scan_btn = QPushButton("▶  Start Scan")
        self._scan_btn.setMinimumHeight(44)
        self._scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scan_btn.setEnabled(False)
        self._scan_btn.setStyleSheet(S.btn_primary())
        self._scan_btn.clicked.connect(self.scan_requested)
        lay.addWidget(self._scan_btn)

        lay.addSpacing(8)

        # Folder section
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {S.BORDER}; border: none;")
        lay.addWidget(sep)

        folder_title = QLabel("Current Folder")
        folder_title.setStyleSheet(f"color: {S.MUTED_DIM}; font-size: 10px; padding-top: 8px; border: none;")
        lay.addWidget(folder_title)

        self._folder_lbl = QLabel("No folder selected")
        self._folder_lbl.setStyleSheet(f"color: {S.MUTED}; font-size: 11px; border: none;")
        self._folder_lbl.setWordWrap(True)
        lay.addWidget(self._folder_lbl)

        self._change_btn = QPushButton("📂  Change Folder")
        self._change_btn.setStyleSheet(S.btn_secondary())
        self._change_btn.setMinimumHeight(36)
        self._change_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self._change_btn)

    def _on_nav(self, index: int):
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == index)
        self.page_changed.emit(index)

    def select_page(self, index: int):
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == index)

    def set_folder(self, folder: str):
        name = os.path.basename(folder) or folder
        self._folder_lbl.setText(f"📁  {name}")
        self._folder_lbl.setToolTip(folder)
        self._folder_lbl.setStyleSheet(f"color: {S.TEXT_SEC}; font-size: 11px; border: none;")
        self._scan_btn.setEnabled(True)

    def set_scanning(self, scanning: bool):
        self._scan_btn.setEnabled(not scanning)
        self._scan_btn.setText("⏳  Scanning..." if scanning else "▶  Start Scan")
        for btn in self._buttons:
            btn.setEnabled(not scanning)


# ── Main Window ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._folder: Optional[str] = None
        self._scan_thread: Optional[QThread] = None
        self._scan_worker: Optional[_ScanWorker] = None
        init_db()
        self._build_ui()
        logger.info("MainWindow initialized.")

    def _build_ui(self):
        self.setWindowTitle("DocuWise — Intelligent Document Manager")
        self.resize(1360, 860)
        self.setMinimumSize(960, 640)
        self.setStyleSheet(S.GLOBAL_QSS)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        self._sidebar = _Sidebar()
        self._sidebar.page_changed.connect(self._on_page_changed)
        self._sidebar.scan_requested.connect(self._on_scan)
        self._sidebar._change_btn.clicked.connect(self._on_browse)
        root.addWidget(self._sidebar)

        # Content area
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)

        self._stack = QStackedWidget()

        self._dashboard   = Dashboard()
        self._documents   = DocumentsView()
        self._duplicates  = DuplicatesView()
        self._image_pdfs  = ImagePdfsView()
        self._cleanup     = CleanupView()
        self._scan_overlay = ScanOverlay()

        self._stack.addWidget(self._dashboard)    # 0
        self._stack.addWidget(self._documents)    # 1
        self._stack.addWidget(self._duplicates)   # 2
        self._stack.addWidget(self._image_pdfs)   # 3
        self._stack.addWidget(self._cleanup)      # 4
        self._stack.addWidget(self._scan_overlay) # 5

        content.addWidget(self._stack, stretch=1)
        root.addLayout(content, stretch=1)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Welcome to DocuWise — choose a folder to begin.")

        # Start on dashboard
        self._sidebar.select_page(_DASHBOARD)
        self._dashboard.refresh()

    # ── Navigation ────────────────────────────────────────────────────────────

    def _on_page_changed(self, index: int):
        self._stack.setCurrentIndex(index)
        self._refresh_current()

    def _refresh_current(self):
        idx = self._stack.currentIndex()
        if idx == _DASHBOARD:
            self._dashboard.refresh()
        elif idx == _DOCUMENTS:
            self._documents.refresh()
        elif idx == _DUPLICATES:
            self._duplicates.refresh()
        elif idx == _IMAGE_PDFS:
            self._image_pdfs.refresh()
        elif idx == _CLEANUP:
            self._cleanup.refresh()

    def _refresh_all(self):
        """Refresh all views after a scan completes."""
        self._dashboard.refresh()
        self._documents.refresh()
        self._duplicates.refresh()
        self._image_pdfs.refresh()
        self._cleanup.refresh()
        logger.info("All views refreshed.")

    def _set_folder_on_views(self, folder: str):
        self._dashboard.set_folder(folder)
        self._documents.set_folder(folder)
        self._duplicates.set_folder(folder)
        self._image_pdfs.set_folder(folder)
        self._cleanup.set_folder(folder)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder to Scan",
            self._folder or os.path.expanduser("~"),
        )
        if folder:
            self._folder = folder
            self._sidebar.set_folder(folder)
            self._set_folder_on_views(folder)
            self._refresh_current()
            self._status.showMessage(f"Folder selected: {folder}")
            logger.info("Folder selected: %s", folder)

    def _on_scan(self):
        if not self._folder:
            QMessageBox.information(self, "No Folder", "Please select a folder first.")
            return
        if self._scan_thread and self._scan_thread.isRunning():
            return

        # Switch to scan overlay
        self._stack.setCurrentIndex(_SCAN)
        self._scan_overlay.start(self._folder)
        self._sidebar.set_scanning(True)
        self._status.showMessage(f"Scanning '{self._folder}'…")

        # Start background thread
        self._scan_thread = QThread()
        self._scan_worker = _ScanWorker(self._folder)
        self._scan_worker.moveToThread(self._scan_thread)

        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.progress.connect(self._scan_overlay.update_progress)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.error.connect(self._scan_thread.quit)

        self._scan_thread.start()

    def _on_scan_finished(self, result: dict):
        self._scan_overlay.stop()
        self._sidebar.set_scanning(False)

        scan    = result.get("scan", {})
        pipe    = result.get("pipeline", {})
        dups    = result.get("duplicates", {})
        missing = result.get("missing", 0)
        cache_hits = pipe.get("cache_hits", 0)

        parts = [
            f"{scan.get('total_files', 0)} files",
            f"{pipe.get('processed', 0)} processed",
            f"{dups.get('duplicates_found', 0)} duplicates",
        ]
        if cache_hits:
            parts.append(f"{cache_hits} cache hits 💾")
        if missing:
            parts.append(f"{missing} missing")
        if pipe.get("failed"):
            parts.append(f"{pipe['failed']} failed")

        self._status.showMessage("✓  Scan complete — " + "  ·  ".join(parts))

        # Refresh all views and navigate to dashboard
        self._refresh_all()
        self._stack.setCurrentIndex(_DASHBOARD)
        self._sidebar.select_page(_DASHBOARD)
        logger.info("Scan finished: %s", result)

    def _on_scan_error(self, msg: str):
        self._scan_overlay.stop()
        self._sidebar.set_scanning(False)
        QMessageBox.critical(self, "Scan Error", f"The scan failed:\n\n{msg}")
        self._status.showMessage("Scan failed.")
        self._stack.setCurrentIndex(_DASHBOARD)
        self._sidebar.select_page(_DASHBOARD)

    # ── Close ─────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.quit()
            self._scan_thread.wait(3000)
        event.accept()
