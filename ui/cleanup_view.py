"""ui/cleanup_view.py — Cleanup workspace for DocuWise."""
from __future__ import annotations
import logging
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QSizePolicy, QTabWidget,
)
from core.database import _connect
from ui.file_actions import open_document, open_folder
from ui import styles as S

logger = logging.getLogger(__name__)


class _CleanupCard(QFrame):
    """A single deletion-candidate card."""

    def __init__(self, filename: str, file_path: str, reason: str,
                 score: int | None, parent_widget=None):
        super().__init__(parent_widget)
        self.setStyleSheet(S.card())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(16)

        # Importance indicator
        sc = int(score) if score is not None else 5
        if sc <= 3:
            indicator_color = S.DANGER
        elif sc <= 6:
            indicator_color = S.WARNING
        else:
            indicator_color = S.SUCCESS

        dot = QLabel(f" {sc}/10 ")
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setStyleSheet(f"""
            background: {indicator_color}22;
            color: {indicator_color};
            border-radius: 6px;
            font-size: 12px;
            font-weight: bold;
            padding: 4px 8px;
            border: none;
        """)
        dot.setFixedWidth(50)
        lay.addWidget(dot)

        # Info
        info = QVBoxLayout()
        info.setSpacing(3)
        name = QLabel(filename)
        name.setStyleSheet(f"color: {S.TEXT}; font-size: 13px; font-weight: 500;")
        name.setWordWrap(True)

        reason_lbl = QLabel(reason or "AI-flagged for cleanup")
        reason_lbl.setStyleSheet(f"color: {S.MUTED}; font-size: 11px;")
        reason_lbl.setWordWrap(True)

        info.addWidget(name)
        info.addWidget(reason_lbl)
        lay.addLayout(info, stretch=1)

        # Actions
        btn_open = QPushButton("Open")
        btn_open.setStyleSheet(S.btn_ghost())
        btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open.clicked.connect(lambda: open_document(file_path, self))
        lay.addWidget(btn_open)

        btn_folder = QPushButton("📁")
        btn_folder.setStyleSheet(S.btn_ghost())
        btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_folder.clicked.connect(lambda: open_folder(file_path, self))
        lay.addWidget(btn_folder)


class _MissingCard(QFrame):
    """Card for a missing file."""

    def __init__(self, filename: str, file_path: str, parent_widget=None):
        super().__init__(parent_widget)
        self.setStyleSheet(f"""
            QFrame {{
                background: {S.PANEL};
                border: 1px solid {S.DANGER}44;
                border-left: 4px solid {S.DANGER};
                border-radius: 12px;
            }}
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(12)

        icon = QLabel("⚠")
        icon.setStyleSheet(f"font-size: 18px; color: {S.DANGER}; border: none;")
        lay.addWidget(icon)

        info = QVBoxLayout()
        info.setSpacing(2)
        name = QLabel(filename)
        name.setStyleSheet(f"color: {S.TEXT}; font-size: 13px;")
        path = QLabel(file_path)
        path.setStyleSheet(f"color: {S.MUTED_DIM}; font-size: 11px;")
        path.setWordWrap(True)
        info.addWidget(name)
        info.addWidget(path)
        lay.addLayout(info, stretch=1)

        badge = QLabel("  Deleted from disk  ")
        badge.setStyleSheet(f"""
            background: {S.DANGER}18;
            color: {S.DANGER};
            border-radius: 6px;
            padding: 3px 10px;
            font-size: 11px;
            font-weight: bold;
        """)
        lay.addWidget(badge)


class CleanupView(QWidget):
    """Tabbed cleanup workspace with deletion candidates and missing files."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # Header
        title = QLabel("Cleanup")
        tf = QFont(); tf.setPointSize(22); tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color: {S.TEXT};")
        root.addWidget(title)

        desc = QLabel("Review files flagged for cleanup by the AI analysis engine.")
        desc.setStyleSheet(f"color: {S.MUTED}; font-size: 13px;")
        root.addWidget(desc)

        # Tabs
        self._tabs = QTabWidget()
        root.addWidget(self._tabs, stretch=1)

        # Deletion candidates tab
        del_widget = QWidget()
        del_lay = QVBoxLayout(del_widget)
        del_lay.setContentsMargins(0, 12, 0, 0)

        del_scroll = QScrollArea()
        del_scroll.setWidgetResizable(True)
        del_scroll.setFrameShape(QFrame.Shape.NoFrame)
        del_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        del_inner = QWidget()
        del_inner.setStyleSheet("background: transparent;")
        self._del_content = QVBoxLayout(del_inner)
        self._del_content.setContentsMargins(0, 0, 0, 0)
        self._del_content.setSpacing(8)
        del_scroll.setWidget(del_inner)
        del_lay.addWidget(del_scroll)
        self._tabs.addTab(del_widget, f"🧹  Candidates")

        # Missing files tab
        miss_widget = QWidget()
        miss_lay = QVBoxLayout(miss_widget)
        miss_lay.setContentsMargins(0, 12, 0, 0)

        miss_scroll = QScrollArea()
        miss_scroll.setWidgetResizable(True)
        miss_scroll.setFrameShape(QFrame.Shape.NoFrame)
        miss_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        miss_inner = QWidget()
        miss_inner.setStyleSheet("background: transparent;")
        self._miss_content = QVBoxLayout(miss_inner)
        self._miss_content.setContentsMargins(0, 0, 0, 0)
        self._miss_content.setSpacing(8)
        miss_scroll.setWidget(miss_inner)
        miss_lay.addWidget(miss_scroll)
        self._tabs.addTab(miss_widget, f"⚠  Missing")

    def set_folder(self, folder: str | None):
        self._folder = folder

    def refresh(self):
        _clear(self._del_content)
        _clear(self._miss_content)
        like = _like(self._folder)

        try:
            conn = _connect()
            if like:
                dels = conn.execute(
                    "SELECT filename, file_path, deletion_reason, importance_score"
                    " FROM documents WHERE deletion_candidate=1 AND file_path LIKE ?"
                    " ORDER BY importance_score ASC", (like,)
                ).fetchall()
                miss = conn.execute(
                    "SELECT filename, file_path FROM documents"
                    " WHERE processing_status='missing' AND file_path LIKE ?"
                    " ORDER BY filename COLLATE NOCASE", (like,)
                ).fetchall()
            else:
                dels = conn.execute(
                    "SELECT filename, file_path, deletion_reason, importance_score"
                    " FROM documents WHERE deletion_candidate=1"
                    " ORDER BY importance_score ASC"
                ).fetchall()
                miss = conn.execute(
                    "SELECT filename, file_path FROM documents"
                    " WHERE processing_status='missing'"
                    " ORDER BY filename COLLATE NOCASE"
                ).fetchall()
            conn.close()
        except Exception:
            dels, miss = [], []

        logger.info("CleanupView: %d candidates, %d missing (folder=%s)",
                     len(dels), len(miss), self._folder)

        for r in dels:
            card = _CleanupCard(r[0], r[1], r[2] or "", r[3], parent_widget=self)
            self._del_content.addWidget(card)
        if not dels:
            empty = QLabel("No cleanup candidates detected.\nAll documents appear valuable.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {S.MUTED_DIM}; font-size: 14px; padding: 60px;")
            self._del_content.addWidget(empty)
        self._del_content.addStretch()

        for r in miss:
            card = _MissingCard(r[0], r[1], parent_widget=self)
            self._miss_content.addWidget(card)
        if not miss:
            empty = QLabel("No missing files — all indexed documents exist on disk.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {S.MUTED_DIM}; font-size: 14px; padding: 60px;")
            self._miss_content.addWidget(empty)
        self._miss_content.addStretch()

        # Update tab labels with counts
        self._tabs.setTabText(0, f"🧹  Candidates ({len(dels)})")
        self._tabs.setTabText(1, f"⚠  Missing ({len(miss)})")


def _like(folder):
    if not folder:
        return None
    return folder.rstrip("\\/") + "\\" + "%"

def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()
