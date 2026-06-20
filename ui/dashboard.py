"""ui/dashboard.py — Modern dashboard landing page for DocuWise."""
from __future__ import annotations
import logging
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QSizePolicy, QScrollArea, QProgressBar, QGridLayout,
)
from core.database import _connect
from ui import styles as S

logger = logging.getLogger(__name__)


class _StatCard(QFrame):
    """A single statistic card with icon, value, and label."""
    def __init__(self, icon: str, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(S.stat_card(color))
        self.setMinimumHeight(100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(16)

        # Icon circle
        icon_lbl = QLabel(icon)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setFixedSize(48, 48)
        icon_lbl.setStyleSheet(f"""
            background: {color}22;
            border-radius: 24px;
            font-size: 22px;
            border: none;
        """)
        lay.addWidget(icon_lbl)

        # Text
        text_lay = QVBoxLayout()
        text_lay.setSpacing(2)
        text_lay.setContentsMargins(0, 0, 0, 0)

        self._val = QLabel("—")
        vf = QFont(); vf.setPointSize(28); vf.setBold(True)
        self._val.setFont(vf)
        self._val.setStyleSheet(f"color: {S.TEXT}; border: none;")

        self._lbl = QLabel(label)
        self._lbl.setStyleSheet(f"color: {S.MUTED}; font-size: 12px; border: none;")

        text_lay.addWidget(self._val)
        text_lay.addWidget(self._lbl)
        lay.addLayout(text_lay)
        lay.addStretch()

    def set_value(self, v):
        self._val.setText(str(v))


class _CategoryBar(QWidget):
    """A single row in the category distribution chart."""
    def __init__(self, category: str, count: int, max_count: int, color: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(12)

        lbl = QLabel(category)
        lbl.setFixedWidth(100)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet(f"color: {S.TEXT_SEC}; font-size: 12px;")

        bar = QProgressBar()
        bar.setRange(0, max_count)
        bar.setValue(count)
        bar.setTextVisible(False)
        bar.setMaximumHeight(10)
        bar.setStyleSheet(f"""
            QProgressBar {{ background: {S.SURFACE}; border: none; border-radius: 5px; }}
            QProgressBar::chunk {{ background: {color}; border-radius: 5px; }}
        """)

        cnt = QLabel(str(count))
        cnt.setFixedWidth(32)
        cnt.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px;")

        lay.addWidget(lbl)
        lay.addWidget(bar, stretch=1)
        lay.addWidget(cnt)


_CAT_COLORS = {
    "Academic": "#3B82F6", "Technical": "#22C55E", "Personal": "#EF4444",
    "Finance": "#F59E0B", "Legal": "#A855F7", "Work": "#06B6D4",
    "Medical": "#EC4899", "Miscellaneous": "#64748B",
}


class Dashboard(QWidget):
    """Main dashboard with stat cards, category distribution, and top documents."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder: str | None = None

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._lay = QVBoxLayout(inner)
        self._lay.setContentsMargins(32, 24, 32, 24)
        self._lay.setSpacing(24)

        # Header
        header = QLabel("Dashboard")
        hf = QFont(); hf.setPointSize(22); hf.setBold(True)
        header.setFont(hf)
        header.setStyleSheet(f"color: {S.TEXT};")
        self._lay.addWidget(header)

        subtitle = QLabel("Overview of your document intelligence")
        subtitle.setStyleSheet(f"color: {S.MUTED}; font-size: 13px;")
        self._lay.addWidget(subtitle)

        # Stat cards row
        cards = QGridLayout()
        cards.setSpacing(16)
        self._c_docs  = _StatCard("📄", "Total Documents",     S.CARD_DOCS)
        self._c_embed = _StatCard("✅", "Fully Processed",     S.CARD_EMBED)
        self._c_dups  = _StatCard("🔁", "Duplicates Found",    S.CARD_DUPS)
        self._c_imgs  = _StatCard("🖼", "Image PDFs",          S.CARD_IMGS)
        self._c_clean = _StatCard("🧹", "Cleanup Candidates",  S.CARD_CLEAN)
        self._c_miss  = _StatCard("⚠", "Missing Files",       S.CARD_MISS)

        cards.addWidget(self._c_docs,  0, 0)
        cards.addWidget(self._c_embed, 0, 1)
        cards.addWidget(self._c_dups,  0, 2)
        cards.addWidget(self._c_imgs,  1, 0)
        cards.addWidget(self._c_clean, 1, 1)
        cards.addWidget(self._c_miss,  1, 2)
        self._lay.addLayout(cards)

        # Category distribution panel
        self._cat_panel = QFrame()
        self._cat_panel.setStyleSheet(S.card())
        self._cat_lay = QVBoxLayout(self._cat_panel)
        self._cat_lay.setContentsMargins(20, 16, 20, 16)
        self._cat_lay.setSpacing(8)
        cat_title = QLabel("Category Distribution")
        ctf = QFont(); ctf.setPointSize(14); ctf.setBold(True)
        cat_title.setFont(ctf)
        cat_title.setStyleSheet(f"color: {S.TEXT}; border: none;")
        self._cat_lay.addWidget(cat_title)
        self._cat_content = QVBoxLayout()
        self._cat_content.setSpacing(4)
        self._cat_lay.addLayout(self._cat_content)
        self._lay.addWidget(self._cat_panel)

        # Recent/top docs panel
        self._top_panel = QFrame()
        self._top_panel.setStyleSheet(S.card())
        self._top_lay = QVBoxLayout(self._top_panel)
        self._top_lay.setContentsMargins(20, 16, 20, 16)
        self._top_lay.setSpacing(8)
        top_title = QLabel("Top Documents by Importance")
        ttf = QFont(); ttf.setPointSize(14); ttf.setBold(True)
        top_title.setFont(ttf)
        top_title.setStyleSheet(f"color: {S.TEXT}; border: none;")
        self._top_lay.addWidget(top_title)
        self._top_content = QVBoxLayout()
        self._top_content.setSpacing(2)
        self._top_lay.addLayout(self._top_content)
        self._lay.addWidget(self._top_panel)

        self._lay.addStretch()
        scroll.setWidget(inner)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def set_folder(self, folder: str | None):
        self._folder = folder

    def refresh(self):
        like = _like(self._folder)
        try:
            conn = _connect()
            if like:
                totals = conn.execute("""
                    SELECT COUNT(*),
                        SUM(CASE WHEN processing_status='embedded'   THEN 1 ELSE 0 END),
                        SUM(CASE WHEN processing_status='image_only' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN deletion_candidate=1           THEN 1 ELSE 0 END),
                        SUM(CASE WHEN processing_status='missing'    THEN 1 ELSE 0 END)
                    FROM documents WHERE file_path LIKE ?""", (like,)).fetchone()
                dups = conn.execute("""
                    SELECT COUNT(*) FROM document_relationships dr
                    JOIN documents d ON d.id=dr.source_document_id
                    WHERE dr.relationship_type='duplicate' AND d.file_path LIKE ?
                """, (like,)).fetchone()
                cats = conn.execute("""
                    SELECT category, COUNT(*) FROM documents
                    WHERE category IS NOT NULL AND file_path LIKE ?
                    GROUP BY category ORDER BY 2 DESC""", (like,)).fetchall()
                top = conn.execute("""
                    SELECT filename, category, importance_score FROM documents
                    WHERE importance_score IS NOT NULL AND file_path LIKE ?
                    ORDER BY importance_score DESC LIMIT 8""", (like,)).fetchall()
            else:
                totals = conn.execute("""
                    SELECT COUNT(*),
                        SUM(CASE WHEN processing_status='embedded'   THEN 1 ELSE 0 END),
                        SUM(CASE WHEN processing_status='image_only' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN deletion_candidate=1           THEN 1 ELSE 0 END),
                        SUM(CASE WHEN processing_status='missing'    THEN 1 ELSE 0 END)
                    FROM documents""").fetchone()
                dups = conn.execute("""
                    SELECT COUNT(*) FROM document_relationships
                    WHERE relationship_type='duplicate'""").fetchone()
                cats = conn.execute("""
                    SELECT category, COUNT(*) FROM documents
                    WHERE category IS NOT NULL
                    GROUP BY category ORDER BY 2 DESC""").fetchall()
                top = conn.execute("""
                    SELECT filename, category, importance_score FROM documents
                    WHERE importance_score IS NOT NULL
                    ORDER BY importance_score DESC LIMIT 8""").fetchall()
            conn.close()
        except Exception:
            logger.exception("Dashboard refresh failed")
            return

        doc_count = totals[0] or 0
        self._c_docs.set_value(doc_count)
        self._c_embed.set_value(totals[1] or 0)
        self._c_dups.set_value(dups[0] or 0)
        self._c_imgs.set_value(totals[2] or 0)
        self._c_clean.set_value(totals[3] or 0)
        self._c_miss.set_value(totals[4] or 0)
        logger.info("Dashboard refresh: %d documents loaded (folder=%s)", doc_count, self._folder)

        # Category bars
        _clear_layout(self._cat_content)
        if cats:
            mx = max(r[1] for r in cats) or 1
            for cat, cnt in cats:
                color = _CAT_COLORS.get(cat, S.MUTED_DIM)
                self._cat_content.addWidget(_CategoryBar(cat, cnt, mx, color))
        else:
            empty = QLabel("No categories yet — run a scan first")
            empty.setStyleSheet(f"color: {S.MUTED_DIM}; font-style: italic; padding: 12px;")
            self._cat_content.addWidget(empty)

        # Top documents
        _clear_layout(self._top_content)
        if top:
            for fname, cat, score in top:
                row = QHBoxLayout()
                row.setSpacing(12)
                name_lbl = QLabel(fname or "—")
                name_lbl.setStyleSheet(f"color: {S.TEXT}; font-size: 13px;")
                cat_lbl = QLabel(cat or "—")
                color = _CAT_COLORS.get(cat, S.MUTED_DIM)
                cat_lbl.setStyleSheet(f"""
                    color: {color}; background: {color}18;
                    border-radius: 4px; padding: 2px 8px; font-size: 11px;
                """)
                cat_lbl.setFixedHeight(22)
                score_lbl = QLabel(f"{int(score)}/10" if score else "—")
                score_lbl.setStyleSheet(f"color: {S.ACCENT}; font-weight: bold; font-size: 13px;")
                score_lbl.setFixedWidth(50)
                score_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                row.addWidget(name_lbl, stretch=1)
                row.addWidget(cat_lbl)
                row.addWidget(score_lbl)
                w = QWidget()
                w.setLayout(row)
                w.setStyleSheet(f"""
                    QWidget {{ background: transparent; border-bottom: 1px solid {S.BORDER}; }}
                    QWidget:hover {{ background: {S.SURFACE}; border-radius: 6px; }}
                """)
                self._top_content.addWidget(w)
        else:
            empty = QLabel("No analyzed documents yet")
            empty.setStyleSheet(f"color: {S.MUTED_DIM}; font-style: italic; padding: 12px;")
            self._top_content.addWidget(empty)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _like(folder: str | None) -> str | None:
    if not folder:
        return None
    return folder.rstrip("\\/") + "\\" + "%"

def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()
        sub = item.layout()
        if sub:
            _clear_layout(sub)
