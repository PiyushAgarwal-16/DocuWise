"""ui/image_pdfs_view.py — Image-only PDF listing for DocuWise."""
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


class _ImagePdfCard(QFrame):
    """Card for a single image-only PDF."""

    def __init__(self, filename: str, file_path: str, size_kb: float,
                 page_count: int | None, parent_widget=None):
        super().__init__(parent_widget)
        self.setStyleSheet(S.card())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(16)

        # Icon
        icon = QLabel("🖼")
        icon.setFixedSize(42, 42)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"""
            background: {S.CARD_IMGS}18;
            border-radius: 21px;
            font-size: 20px;
            border: none;
        """)
        lay.addWidget(icon)

        # Info
        info = QVBoxLayout()
        info.setSpacing(3)
        name = QLabel(filename)
        name.setStyleSheet(f"color: {S.TEXT}; font-size: 13px; font-weight: 500;")
        name.setWordWrap(True)

        meta_parts = []
        if page_count:
            meta_parts.append(f"{page_count} pages")
        if size_kb:
            sz = f"{size_kb/1024:.1f} MB" if size_kb >= 1024 else f"{size_kb:.0f} KB"
            meta_parts.append(sz)
        meta_parts.append("No extractable text")
        meta = QLabel("  ·  ".join(meta_parts))
        meta.setStyleSheet(f"color: {S.MUTED}; font-size: 11px;")

        info.addWidget(name)
        info.addWidget(meta)
        lay.addLayout(info, stretch=1)

        # Status badge
        badge = QLabel("  OCR Required  ")
        badge.setStyleSheet(f"""
            background: {S.CARD_IMGS}22;
            color: {S.CARD_IMGS};
            border-radius: 6px;
            padding: 3px 10px;
            font-size: 11px;
            font-weight: bold;
        """)
        lay.addWidget(badge)

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


class ImagePdfsView(QWidget):
    """List of image-only PDFs with OCR status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # Header
        header_row = QHBoxLayout()
        title = QLabel("Image PDFs")
        tf = QFont(); tf.setPointSize(22); tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color: {S.TEXT};")
        header_row.addWidget(title)
        header_row.addStretch()

        self._count_lbl = QLabel()
        self._count_lbl.setStyleSheet(f"color: {S.MUTED}; font-size: 13px;")
        header_row.addWidget(self._count_lbl)
        root.addLayout(header_row)

        desc = QLabel("These PDFs contain only scanned images — no machine-readable text was found.")
        desc.setStyleSheet(f"color: {S.MUTED}; font-size: 13px;")
        desc.setWordWrap(True)
        root.addWidget(desc)

        # Scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._content = QVBoxLayout(self._inner)
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(8)
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
                rows = conn.execute(
                    "SELECT filename, file_path, file_size_kb, word_count FROM documents"
                    " WHERE processing_status='image_only' AND file_path LIKE ?"
                    " ORDER BY filename COLLATE NOCASE", (like,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT filename, file_path, file_size_kb, word_count FROM documents"
                    " WHERE processing_status='image_only'"
                    " ORDER BY filename COLLATE NOCASE"
                ).fetchall()
            conn.close()
        except Exception:
            rows = []

        logger.info("ImagePdfsView loaded %d documents (folder=%s)", len(rows), self._folder)

        for r in rows:
            card = _ImagePdfCard(r[0], r[1], r[2] or 0, None, parent_widget=self)
            self._content.addWidget(card)

        if not rows:
            empty = QLabel("No image-only PDFs found.\nAll PDFs have extractable text content.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {S.MUTED_DIM}; font-size: 14px; padding: 60px;")
            self._content.addWidget(empty)

        self._content.addStretch()
        self._count_lbl.setText(f"{len(rows)} file{'s' if len(rows)!=1 else ''}")


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
