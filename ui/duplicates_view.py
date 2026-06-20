"""ui/duplicates_view.py — Visual duplicate groups display for DocuWise."""
from __future__ import annotations
import logging
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QSizePolicy,
)
from core.database import _connect
from ui.file_actions import open_document, open_folder
from ui import styles as S

logger = logging.getLogger(__name__)


class _DupCard(QFrame):
    """A single duplicate-pair card with similarity badge and action buttons."""

    def __init__(self, file_a: str, path_a: str, file_b: str, path_b: str,
                 score: float, rel_type: str, size_kb: float, parent_widget=None):
        super().__init__(parent_widget)
        self.setStyleSheet(S.card())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        # Top row: type badge + similarity
        top = QHBoxLayout()
        top.setSpacing(10)

        is_dup = rel_type == "duplicate"
        badge_color = S.DANGER if is_dup else S.WARNING
        badge_text = "Duplicate" if is_dup else "Similar"
        badge = QLabel(f"  {badge_text}  ")
        badge.setStyleSheet(f"""
            background: {badge_color}22;
            color: {badge_color};
            border-radius: 6px;
            padding: 3px 10px;
            font-size: 11px;
            font-weight: bold;
        """)
        top.addWidget(badge)
        top.addStretch()

        pct = QLabel(f"{score*100:.1f}%")
        pf = QFont(); pf.setPointSize(18); pf.setBold(True)
        pct.setFont(pf)
        pct.setStyleSheet(f"color: {badge_color};")
        pct_lbl = QLabel("match")
        pct_lbl.setStyleSheet(f"color: {S.MUTED}; font-size: 11px;")

        top.addWidget(pct)
        top.addWidget(pct_lbl)
        lay.addLayout(top)

        # File comparison row
        comp = QHBoxLayout()
        comp.setSpacing(16)

        def file_block(fname, fpath):
            f = QFrame()
            f.setStyleSheet(f"""
                QFrame {{
                    background: {S.SURFACE};
                    border-radius: 8px;
                    border: 1px solid {S.BORDER};
                }}
            """)
            fl = QVBoxLayout(f)
            fl.setContentsMargins(14, 10, 14, 10)
            fl.setSpacing(4)

            name = QLabel(f"📄  {fname}")
            name.setStyleSheet(f"color: {S.TEXT}; font-size: 13px; font-weight: 500; border: none;")
            name.setWordWrap(True)

            import os
            folder_name = os.path.dirname(fpath)
            path_lbl = QLabel(folder_name)
            path_lbl.setStyleSheet(f"color: {S.MUTED_DIM}; font-size: 11px; border: none;")
            path_lbl.setWordWrap(True)

            btns = QHBoxLayout()
            btns.setSpacing(6)
            btn_open = QPushButton("Open")
            btn_open.setStyleSheet(S.btn_ghost())
            btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_open.clicked.connect(lambda: open_document(fpath, self))
            btn_folder = QPushButton("📁 Folder")
            btn_folder.setStyleSheet(S.btn_ghost())
            btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_folder.clicked.connect(lambda: open_folder(fpath, self))
            btns.addWidget(btn_open)
            btns.addWidget(btn_folder)
            btns.addStretch()

            fl.addWidget(name)
            fl.addWidget(path_lbl)
            fl.addLayout(btns)
            return f

        comp.addWidget(file_block(file_a, path_a), stretch=1)

        # VS separator
        vs = QLabel("⟷")
        vs.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vs.setStyleSheet(f"color: {S.MUTED_DIM}; font-size: 20px;")
        vs.setFixedWidth(40)
        comp.addWidget(vs)

        comp.addWidget(file_block(file_b, path_b), stretch=1)
        lay.addLayout(comp)

        # Size info
        if size_kb and size_kb > 0:
            size_str = f"{size_kb/1024:.1f} MB" if size_kb >= 1024 else f"{size_kb:.0f} KB"
            info = QLabel(f"💾  Potential savings: {size_str}")
            info.setStyleSheet(f"color: {S.WARNING}; font-size: 11px;")
            lay.addWidget(info)


class DuplicatesView(QWidget):
    """Scrollable list of duplicate-pair cards."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # Header
        header_row = QHBoxLayout()
        title = QLabel("Duplicates")
        tf = QFont(); tf.setPointSize(22); tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color: {S.TEXT};")
        header_row.addWidget(title)
        header_row.addStretch()

        self._savings_lbl = QLabel()
        self._savings_lbl.setStyleSheet(f"""
            color: {S.DANGER};
            background: {S.DANGER}15;
            border-radius: 8px;
            padding: 6px 16px;
            font-size: 13px;
            font-weight: bold;
        """)
        self._savings_lbl.setVisible(False)
        header_row.addWidget(self._savings_lbl)

        self._count_lbl = QLabel()
        self._count_lbl.setStyleSheet(f"color: {S.MUTED}; font-size: 13px;")
        header_row.addWidget(self._count_lbl)
        root.addLayout(header_row)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._content = QVBoxLayout(self._inner)
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(12)
        scroll.setWidget(self._inner)

        root.addWidget(scroll, stretch=1)

    def set_folder(self, folder: str | None):
        self._folder = folder

    def refresh(self):
        _clear(self._content)
        like = _like(self._folder)
        try:
            conn = _connect()
            if like:
                rows = conn.execute("""
                    SELECT d1.filename, d1.file_path, d2.filename, d2.file_path,
                           d2.file_size_kb, dr.similarity_score, dr.relationship_type
                    FROM document_relationships dr
                    JOIN documents d1 ON d1.id=dr.source_document_id
                    JOIN documents d2 ON d2.id=dr.target_document_id
                    WHERE dr.relationship_type IN ('duplicate','similar')
                      AND d1.file_path LIKE ?
                    ORDER BY dr.similarity_score DESC""", (like,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT d1.filename, d1.file_path, d2.filename, d2.file_path,
                           d2.file_size_kb, dr.similarity_score, dr.relationship_type
                    FROM document_relationships dr
                    JOIN documents d1 ON d1.id=dr.source_document_id
                    JOIN documents d2 ON d2.id=dr.target_document_id
                    WHERE dr.relationship_type IN ('duplicate','similar')
                    ORDER BY dr.similarity_score DESC""").fetchall()
            conn.close()
        except Exception:
            rows = []

        logger.info("DuplicatesView loaded %d pairs (folder=%s)", len(rows), self._folder)

        savings = 0.0
        for r in rows:
            card = _DupCard(r[0], r[1], r[2], r[3], r[5], r[6], r[4] or 0, parent_widget=self)
            self._content.addWidget(card)
            if r[6] == "duplicate":
                savings += r[4] or 0

        if not rows:
            empty = QLabel("No duplicates detected yet.\nRun a scan to detect similar documents.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {S.MUTED_DIM}; font-size: 14px; padding: 60px;")
            self._content.addWidget(empty)

        self._content.addStretch()

        self._count_lbl.setText(f"{len(rows)} pair{'s' if len(rows)!=1 else ''}")

        if savings > 0:
            s = f"{savings/1024:.1f} MB" if savings >= 1024 else f"{savings:.0f} KB"
            self._savings_lbl.setText(f"💾  Potential space savings: {s}")
            self._savings_lbl.setVisible(True)
        else:
            self._savings_lbl.setVisible(False)


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
