"""ui/home_screen.py — Home/landing screen for DocuWise."""
from __future__ import annotations
import os
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy, QFileDialog,
)
from core.database import _connect


class StatCard(QFrame):
    def __init__(self, label: str, color: str = "#2c3e50", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"""
            QFrame {{
                background: white;
                border: 1px solid #e0e0e0;
                border-radius: 10px;
                border-left: 4px solid {color};
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)
        self._val = QLabel("—")
        vf = QFont(); vf.setPointSize(26); vf.setBold(True)
        self._val.setFont(vf)
        self._val.setStyleSheet(f"color: {color}; border: none;")
        self._val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl = QLabel(label)
        lf = QFont(); lf.setPointSize(9)
        self._lbl.setFont(lf)
        self._lbl.setStyleSheet("color: #888; border: none;")
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._val)
        lay.addWidget(self._lbl)

    def set_value(self, v): self._val.setText(str(v))


class HomeScreen(QWidget):
    folder_selected = pyqtSignal(str)
    scan_requested  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder: str | None = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(60, 40, 60, 40)
        root.setSpacing(24)

        # Title
        title = QLabel("DocuWise")
        tf = QFont(); tf.setPointSize(32); tf.setBold(True)
        title.setFont(tf)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #1a1a2e;")
        sub = QLabel("Intelligent Document Manager")
        sf = QFont(); sf.setPointSize(12)
        sub.setFont(sf)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #888;")
        root.addWidget(title)
        root.addWidget(sub)

        # Divider
        div = QFrame(); div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("color: #e0e0e0;")
        root.addWidget(div)

        # Folder row
        folder_row = QHBoxLayout()
        self._folder_lbl = QLabel("No folder selected")
        self._folder_lbl.setStyleSheet("color: #555; font-style: italic; font-size: 11pt;")
        self._folder_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._btn_change = QPushButton("📂  Choose Folder")
        self._btn_change.setMinimumHeight(38)
        self._btn_change.setStyleSheet("""
            QPushButton {
                background: #f0f0f0; border: 1px solid #ccc; border-radius: 6px;
                padding: 6px 18px; font-size: 10pt;
            }
            QPushButton:hover { background: #e0e0e0; }
        """)
        self._btn_change.clicked.connect(self._on_browse)
        folder_row.addWidget(self._folder_lbl, stretch=1)
        folder_row.addWidget(self._btn_change)
        root.addLayout(folder_row)

        # Stat cards
        card_row = QHBoxLayout()
        card_row.setSpacing(12)
        self._c_docs  = StatCard("Documents",    "#2980b9")
        self._c_dups  = StatCard("Duplicates",   "#e74c3c")
        self._c_imgs  = StatCard("Image PDFs",   "#8e44ad")
        self._c_clean = StatCard("Can Delete",   "#e67e22")
        for c in [self._c_docs, self._c_dups, self._c_imgs, self._c_clean]:
            card_row.addWidget(c)
        root.addLayout(card_row)

        root.addStretch(1)

        # Scan button
        self._btn_scan = QPushButton("▶   Start Scan")
        self._btn_scan.setEnabled(False)
        self._btn_scan.setMinimumHeight(56)
        self._btn_scan.setStyleSheet("""
            QPushButton {
                background: #2c3e8c; color: white; border: none;
                border-radius: 10px; font-size: 15pt; font-weight: bold;
            }
            QPushButton:hover  { background: #1a2a6c; }
            QPushButton:disabled { background: #bdc3c7; color: #888; }
        """)
        self._btn_scan.clicked.connect(self.scan_requested)
        root.addWidget(self._btn_scan)

        root.addStretch(1)

    # ── Public ────────────────────────────────────────────────────────────────

    def refresh_stats(self, folder: str | None = None):
        f = folder or self._folder
        try:
            conn = _connect()
            if f:
                like = f.rstrip("\\/") + "\\" + "%"
                row = conn.execute("""
                    SELECT COUNT(*),
                        SUM(CASE WHEN processing_status='image_only' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN deletion_candidate=1 THEN 1 ELSE 0 END)
                    FROM documents
                    WHERE file_path LIKE ?
                """, (like,)).fetchone()
                dup = conn.execute("""
                    SELECT COUNT(*) FROM document_relationships dr
                    JOIN documents d1 ON d1.id=dr.source_document_id
                    WHERE dr.relationship_type='duplicate'
                    AND d1.file_path LIKE ?
                """, (like,)).fetchone()
            else:
                row = conn.execute("""
                    SELECT COUNT(*),
                        SUM(CASE WHEN processing_status='image_only' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN deletion_candidate=1 THEN 1 ELSE 0 END)
                    FROM documents
                """).fetchone()
                dup = conn.execute("""
                    SELECT COUNT(*) FROM document_relationships
                    WHERE relationship_type='duplicate'
                """).fetchone()
            conn.close()
            self._c_docs.set_value(row[0] or 0)
            self._c_dups.set_value(dup[0] or 0)
            self._c_imgs.set_value(row[1] or 0)
            self._c_clean.set_value(row[2] or 0)
        except Exception:
            pass


    def set_folder(self, folder: str):
        self._folder = folder
        name = os.path.basename(folder) or folder
        self._folder_lbl.setText(f"📁  {name}   ({folder})")
        self._folder_lbl.setStyleSheet("color: #1a1a2e; font-style: normal; font-size: 11pt;")
        self._btn_scan.setEnabled(True)
        self.refresh_stats(folder)

    # ── Private ───────────────────────────────────────────────────────────────

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder to Scan",
            self._folder or os.path.expanduser("~"),
        )
        if folder:
            self.set_folder(folder)
            self.folder_selected.emit(folder)
