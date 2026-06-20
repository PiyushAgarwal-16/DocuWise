"""ui/results_screen.py — Tabbed results view for DocuWise."""
from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel,
    QProgressBar, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QFrame, QScrollArea,
)
from core.database import _connect
from ui.document_table import DocumentTableWidget
from ui.file_actions import make_context_menu, open_document


_CAT_COLORS = {
    "Academic": "#3498db", "Technical": "#2ecc71", "Personal": "#e74c3c",
    "Finance": "#f39c12", "Legal": "#9b59b6", "Work": "#1abc9c",
    "Medical": "#e91e63", "Miscellaneous": "#95a5a6",
}


def _simple_tree(headers: list[str]) -> QTreeWidget:
    t = QTreeWidget()
    t.setHeaderLabels(headers)
    t.setAlternatingRowColors(True)
    t.setRootIsDecorated(False)
    h = t.header()
    for i in range(len(headers) - 1):
        h.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
    h.setSectionResizeMode(len(headers)-1, QHeaderView.ResizeMode.ResizeToContents)
    return t


# ── DB helpers ────────────────────────────────────────────────────────────────
# All folder filtering now uses direct LIKE with backslash-native paths and
# parameterised queries (no string interpolation) to prevent SQL injection.

def _folder_like(folder: str | None) -> str | None:
    """Return a LIKE pattern for files inside *folder*, or None."""
    if not folder:
        return None
    return folder.rstrip("\\/") + "\\" + "%"


# ── Overview Tab ─────────────────────────────────────────────────────────────

class OverviewTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self._lay = QVBoxLayout(inner)
        self._lay.setSpacing(20)
        self._lay.setContentsMargins(16, 16, 16, 16)
        scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def _clear(self):
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            # Also handle spacer items so they don't accumulate across refreshes
            del item

    def _section(self, title: str) -> QVBoxLayout:
        box = QFrame()
        box.setStyleSheet("QFrame { background: white; border: 1px solid #e8e8e8; border-radius: 8px; }")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)
        lbl = QLabel(title)
        f = QFont(); f.setPointSize(11); f.setBold(True)
        lbl.setFont(f)
        lbl.setStyleSheet("color: #1a1a2e; border: none;")
        lay.addWidget(lbl)
        self._lay.addWidget(box)
        return lay

    def refresh(self, folder: str | None = None):
        self._clear()
        like = _folder_like(folder)
        try:
            conn = _connect()
            if like:
                totals = conn.execute("""
                    SELECT COUNT(*),
                        SUM(CASE WHEN processing_status='embedded'   THEN 1 ELSE 0 END),
                        SUM(CASE WHEN processing_status='image_only' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN deletion_candidate=1           THEN 1 ELSE 0 END),
                        SUM(CASE WHEN processing_status='missing'    THEN 1 ELSE 0 END),
                        SUM(CASE WHEN processing_status='failed'     THEN 1 ELSE 0 END)
                    FROM documents WHERE file_path LIKE ?""", (like,)).fetchone()
                dups = conn.execute("""
                    SELECT COUNT(*) FROM document_relationships dr
                    JOIN documents d ON d.id=dr.source_document_id
                    WHERE dr.relationship_type='duplicate'
                      AND d.file_path LIKE ?""", (like,)).fetchone()
                cats = conn.execute("""
                    SELECT category, COUNT(*) FROM documents
                    WHERE category IS NOT NULL AND file_path LIKE ?
                    GROUP BY category ORDER BY 2 DESC""", (like,)).fetchall()
                subjects = conn.execute("""
                    SELECT subject, category, importance_score FROM documents
                    WHERE subject IS NOT NULL AND importance_score IS NOT NULL
                      AND file_path LIKE ?
                    ORDER BY importance_score DESC LIMIT 10""", (like,)).fetchall()
            else:
                totals = conn.execute("""
                    SELECT COUNT(*),
                        SUM(CASE WHEN processing_status='embedded'   THEN 1 ELSE 0 END),
                        SUM(CASE WHEN processing_status='image_only' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN deletion_candidate=1           THEN 1 ELSE 0 END),
                        SUM(CASE WHEN processing_status='missing'    THEN 1 ELSE 0 END),
                        SUM(CASE WHEN processing_status='failed'     THEN 1 ELSE 0 END)
                    FROM documents""").fetchone()
                dups = conn.execute("""
                    SELECT COUNT(*) FROM document_relationships
                    WHERE relationship_type='duplicate'""").fetchone()
                cats = conn.execute("""
                    SELECT category, COUNT(*) FROM documents
                    WHERE category IS NOT NULL
                    GROUP BY category ORDER BY 2 DESC""").fetchall()
                subjects = conn.execute("""
                    SELECT subject, category, importance_score FROM documents
                    WHERE subject IS NOT NULL AND importance_score IS NOT NULL
                    ORDER BY importance_score DESC LIMIT 10""").fetchall()
            conn.close()
        except Exception:
            return

        # Summary cards row
        cards_lay = self._section("Summary")
        row = QHBoxLayout()
        row.setSpacing(10)
        def mini(label, val, color):
            f = QFrame()
            f.setStyleSheet(f"QFrame {{ border: none; border-left: 3px solid {color}; padding-left: 8px; }}")
            v = QVBoxLayout(f); v.setContentsMargins(0,0,0,0); v.setSpacing(2)
            n = QLabel(str(val)); nf = QFont(); nf.setPointSize(20); nf.setBold(True)
            n.setFont(nf); n.setStyleSheet(f"color:{color}; border:none;")
            l = QLabel(label); l.setStyleSheet("color:#888; font-size:8pt; border:none;")
            v.addWidget(n); v.addWidget(l)
            return f
        row.addWidget(mini("Documents",  totals[0] or 0, "#2980b9"))
        row.addWidget(mini("Embedded",   totals[1] or 0, "#27ae60"))
        row.addWidget(mini("Duplicates", dups[0]  or 0, "#e74c3c"))
        row.addWidget(mini("Image PDFs", totals[2] or 0, "#8e44ad"))
        row.addWidget(mini("Can Delete", totals[3] or 0, "#e67e22"))
        row.addWidget(mini("Missing",    totals[4] or 0, "#d35400"))
        cards_lay.addLayout(row)

        # Category distribution
        if cats:
            cat_lay = self._section("Category Distribution")
            max_cnt = max(r[1] for r in cats) or 1
            for cat, cnt in cats:
                rw = QHBoxLayout(); rw.setSpacing(8)
                lbl = QLabel(cat); lbl.setFixedWidth(100)
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                bar = QProgressBar(); bar.setRange(0, max_cnt); bar.setValue(cnt)
                bar.setTextVisible(False); bar.setMaximumHeight(14)
                color = _CAT_COLORS.get(cat, "#7f8c8d")
                bar.setStyleSheet(f"QProgressBar{{border:1px solid #eee;border-radius:3px;background:#f5f5f5;}}"
                                  f"QProgressBar::chunk{{background:{color};border-radius:2px;}}")
                cl = QLabel(str(cnt)); cl.setFixedWidth(30)
                cl.setStyleSheet(f"color:{color}; font-weight:bold;")
                rw.addWidget(lbl); rw.addWidget(bar, stretch=1); rw.addWidget(cl)
                rw_w = QWidget(); rw_w.setLayout(rw)
                cat_lay.addWidget(rw_w)

        # Top subjects
        if subjects:
            subj_lay = self._section("Top Documents by Importance")
            tree = _simple_tree(["Document", "Category", "Score"])
            for subj, cat, score in subjects:
                item = QTreeWidgetItem([subj or "—", cat or "—", str(score or "—")])
                tree.addTopLevelItem(item)
            subj_lay.addWidget(tree)

        self._lay.addStretch(1)


# ── Duplicates Tab ────────────────────────────────────────────────────────────

class DuplicatesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self._savings_lbl = QLabel()
        self._savings_lbl.setStyleSheet("color:#c0392b; font-weight:bold; padding:4px 8px;")
        self._savings_lbl.setVisible(False)
        lay.addWidget(self._savings_lbl)
        self._tree = _simple_tree(["File A", "File B", "Score", "Type"])
        self._tree.itemDoubleClicked.connect(
            lambda item, col: open_document(item.data(col, Qt.ItemDataRole.UserRole) or "", self)
        )
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._ctx)
        lay.addWidget(self._tree)

    def _ctx(self, pos):
        item = self._tree.itemAt(pos)
        if not item: return
        fp = item.data(1, Qt.ItemDataRole.UserRole) or ""
        if fp:
            make_context_menu(fp, self).exec(self._tree.viewport().mapToGlobal(pos))

    def refresh(self, folder: str | None = None):
        self._tree.clear()
        like = _folder_like(folder)
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
        savings = 0.0
        for r in rows:
            item = QTreeWidgetItem([r[0], r[2], f"{r[5]:.3f}", r[6]])
            item.setData(0, Qt.ItemDataRole.UserRole, r[1])
            item.setData(1, Qt.ItemDataRole.UserRole, r[3])
            if r[6] == "duplicate":
                for c in range(4): item.setForeground(c, QColor("#c0392b"))
                savings += r[4] or 0
            self._tree.addTopLevelItem(item)
        if savings > 0:
            s = f"{savings/1024:.1f} MB" if savings >= 1024 else f"{savings:.0f} KB"
            self._savings_lbl.setText(f"💾  Potential space savings: {s}")
            self._savings_lbl.setVisible(True)
        else:
            self._savings_lbl.setVisible(False)


# ── Cleanup Tab ───────────────────────────────────────────────────────────────

class CleanupTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        lbl = QLabel("Image-only PDFs  (OCR required)")
        lbl.setStyleSheet("font-weight: bold; color: #8e44ad;")
        lay.addWidget(lbl)
        self._img_tree = _simple_tree(["Filename", "Path"])
        self._img_tree.itemDoubleClicked.connect(
            lambda item, _: open_document(item.data(0, Qt.ItemDataRole.UserRole) or "", self)
        )
        self._img_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._img_tree.customContextMenuRequested.connect(
            lambda pos: self._ctx(self._img_tree, pos)
        )
        lay.addWidget(self._img_tree)

        lbl2 = QLabel("Deletion Candidates  (low value / AI-flagged)")
        lbl2.setStyleSheet("font-weight: bold; color: #e67e22;")
        lay.addWidget(lbl2)
        self._del_tree = _simple_tree(["Filename", "Reason", "Score"])
        self._del_tree.itemDoubleClicked.connect(
            lambda item, _: open_document(item.data(0, Qt.ItemDataRole.UserRole) or "", self)
        )
        self._del_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._del_tree.customContextMenuRequested.connect(
            lambda pos: self._ctx(self._del_tree, pos)
        )
        lay.addWidget(self._del_tree)

        lbl3 = QLabel("Missing Files  (deleted from disk)")
        lbl3.setStyleSheet("font-weight: bold; color: #d35400;")
        lay.addWidget(lbl3)
        self._miss_tree = _simple_tree(["Filename", "Original Path"])
        self._miss_tree.itemDoubleClicked.connect(
            lambda item, _: open_document(item.data(0, Qt.ItemDataRole.UserRole) or "", self)
        )
        self._miss_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._miss_tree.customContextMenuRequested.connect(
            lambda pos: self._ctx(self._miss_tree, pos)
        )
        lay.addWidget(self._miss_tree)

    def _ctx(self, tree, pos):
        item = tree.itemAt(pos)
        if not item: return
        fp = item.data(0, Qt.ItemDataRole.UserRole) or ""
        if fp:
            make_context_menu(fp, self).exec(tree.viewport().mapToGlobal(pos))

    def refresh(self, folder: str | None = None):
        for tree in [self._img_tree, self._del_tree, self._miss_tree]:
            tree.clear()
        like = _folder_like(folder)
        try:
            conn = _connect()
            if like:
                imgs = conn.execute(
                    "SELECT filename, file_path FROM documents"
                    " WHERE processing_status='image_only' AND file_path LIKE ?"
                    " ORDER BY filename COLLATE NOCASE", (like,)
                ).fetchall()
                dels = conn.execute(
                    "SELECT filename, file_path, deletion_reason, importance_score FROM documents"
                    " WHERE deletion_candidate=1 AND file_path LIKE ?"
                    " ORDER BY importance_score ASC", (like,)
                ).fetchall()
                miss = conn.execute(
                    "SELECT filename, file_path FROM documents"
                    " WHERE processing_status='missing' AND file_path LIKE ?"
                    " ORDER BY filename COLLATE NOCASE", (like,)
                ).fetchall()
            else:
                imgs = conn.execute(
                    "SELECT filename, file_path FROM documents"
                    " WHERE processing_status='image_only'"
                    " ORDER BY filename COLLATE NOCASE"
                ).fetchall()
                dels = conn.execute(
                    "SELECT filename, file_path, deletion_reason, importance_score FROM documents"
                    " WHERE deletion_candidate=1"
                    " ORDER BY importance_score ASC"
                ).fetchall()
                miss = conn.execute(
                    "SELECT filename, file_path FROM documents"
                    " WHERE processing_status='missing'"
                    " ORDER BY filename COLLATE NOCASE"
                ).fetchall()
            conn.close()
        except Exception:
            return
        for r in imgs:
            item = QTreeWidgetItem([r[0], r[1]])
            item.setData(0, Qt.ItemDataRole.UserRole, r[1])
            self._img_tree.addTopLevelItem(item)
        for r in dels:
            item = QTreeWidgetItem([r[0], r[2] or "—", str(r[3] or "—")])
            item.setData(0, Qt.ItemDataRole.UserRole, r[1])
            item.setForeground(0, QColor("#e67e22"))
            self._del_tree.addTopLevelItem(item)
        for r in miss:
            item = QTreeWidgetItem([r[0], r[1]])
            item.setData(0, Qt.ItemDataRole.UserRole, r[1])
            item.setForeground(0, QColor("#c0392b"))
            self._miss_tree.addTopLevelItem(item)


# ── Results Screen ────────────────────────────────────────────────────────────

class ResultsScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab { padding: 8px 20px; font-size: 10pt; }
            QTabBar::tab:selected { border-bottom: 2px solid #2c3e8c; font-weight: bold; color: #2c3e8c; }
        """)
        self._overview  = OverviewTab()
        self._documents = DocumentTableWidget()
        self._dups      = DuplicatesTab()
        self._cleanup   = CleanupTab()
        self._tabs.addTab(self._overview,  "📊  Overview")
        self._tabs.addTab(self._documents, "📄  Documents")
        self._tabs.addTab(self._dups,      "🔁  Duplicates")
        self._tabs.addTab(self._cleanup,   "🧹  Cleanup")
        lay.addWidget(self._tabs)

    def set_folder(self, folder: str):
        self._folder = folder
        # Only store the filter — don't trigger a refresh here.
        # refresh() will be called immediately after by the caller.
        self._documents._folder_filter = folder

    def refresh(self):
        f = self._folder
        self._overview.refresh(f)
        self._documents.refresh()
        self._dups.refresh(f)
        self._cleanup.refresh(f)
