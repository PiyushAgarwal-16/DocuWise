"""ui/styles.py — Centralized dark theme for DocuWise."""

# ── Color palette ────────────────────────────────────────────────────────────
BG         = "#0F172A"
PANEL      = "#1E293B"
PANEL_ALT  = "#273548"
SURFACE    = "#334155"
BORDER     = "#334155"
ACCENT     = "#8B5CF6"
ACCENT_DIM = "#7C3AED"
SUCCESS    = "#22C55E"
WARNING    = "#F59E0B"
DANGER     = "#EF4444"
INFO       = "#3B82F6"
TEXT       = "#F8FAFC"
TEXT_SEC   = "#CBD5E1"
MUTED      = "#94A3B8"
MUTED_DIM  = "#64748B"

# ── Card colours ─────────────────────────────────────────────────────────────
CARD_DOCS  = "#3B82F6"
CARD_DUPS  = "#EF4444"
CARD_IMGS  = "#A855F7"
CARD_CLEAN = "#F59E0B"
CARD_EMBED = "#22C55E"
CARD_MISS  = "#F97316"

# ── Fonts ────────────────────────────────────────────────────────────────────
FONT       = "'Segoe UI', 'Inter', 'Roboto', sans-serif"

# ── Global QSS ──────────────────────────────────────────────────────────────
GLOBAL_QSS = f"""
    * {{
        font-family: {FONT};
        color: {TEXT};
    }}
    QMainWindow, QWidget {{
        background: {BG};
    }}
    QScrollBar:vertical {{
        background: {PANEL};
        width: 8px;
        border: none;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {SURFACE};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {MUTED_DIM};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: {PANEL};
        height: 8px;
        border: none;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {SURFACE};
        border-radius: 4px;
        min-width: 30px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QToolTip {{
        background: {PANEL};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 10px;
    }}
    QMenu {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background: {SURFACE};
    }}
    QStatusBar {{
        background: {PANEL};
        color: {MUTED};
        font-size: 11px;
        border-top: 1px solid {BORDER};
    }}
    QHeaderView::section {{
        background: {PANEL};
        color: {MUTED};
        border: none;
        border-bottom: 1px solid {BORDER};
        padding: 6px 12px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
    }}
    QTableView, QTreeWidget {{
        background: {PANEL};
        alternate-background-color: {PANEL_ALT};
        border: 1px solid {BORDER};
        border-radius: 8px;
        gridline-color: {BORDER};
        selection-background-color: {ACCENT_DIM};
        selection-color: {TEXT};
        outline: none;
    }}
    QTableView::item, QTreeWidget::item {{
        padding: 4px 8px;
        border: none;
    }}
    QTableView::item:hover, QTreeWidget::item:hover {{
        background: {SURFACE};
    }}
    QLineEdit {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 8px 12px;
        color: {TEXT};
        font-size: 13px;
        selection-background-color: {ACCENT};
    }}
    QLineEdit:focus {{
        border: 1px solid {ACCENT};
    }}
    QComboBox {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 6px 12px;
        color: {TEXT};
        min-width: 120px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 6px;
        selection-background-color: {SURFACE};
    }}
    QProgressBar {{
        background: {SURFACE};
        border: none;
        border-radius: 6px;
        text-align: center;
        color: {TEXT};
        font-size: 11px;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {ACCENT}, stop:1 {INFO});
        border-radius: 6px;
    }}
    QTabWidget::pane {{
        border: none;
        background: transparent;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {MUTED};
        padding: 8px 18px;
        border: none;
        border-bottom: 2px solid transparent;
        font-size: 13px;
    }}
    QTabBar::tab:selected {{
        color: {ACCENT};
        border-bottom: 2px solid {ACCENT};
        font-weight: bold;
    }}
    QTabBar::tab:hover {{
        color: {TEXT};
    }}
"""

# ── Reusable component styles ───────────────────────────────────────────────

def btn_primary() -> str:
    return f"""
        QPushButton {{
            background: {ACCENT};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 10px 24px;
            font-size: 13px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background: {ACCENT_DIM}; }}
        QPushButton:pressed {{ background: #6D28D9; }}
        QPushButton:disabled {{ background: {SURFACE}; color: {MUTED_DIM}; }}
    """

def btn_secondary() -> str:
    return f"""
        QPushButton {{
            background: {SURFACE};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 8px;
            padding: 8px 18px;
            font-size: 13px;
        }}
        QPushButton:hover {{ background: {PANEL_ALT}; border-color: {MUTED_DIM}; }}
    """

def btn_ghost() -> str:
    return f"""
        QPushButton {{
            background: transparent;
            color: {MUTED};
            border: none;
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 12px;
        }}
        QPushButton:hover {{ background: {SURFACE}; color: {TEXT}; }}
    """

def card(accent: str = ACCENT) -> str:
    return f"""
        QFrame {{
            background: {PANEL};
            border: 1px solid {BORDER};
            border-radius: 12px;
        }}
    """

def stat_card(accent: str) -> str:
    return f"""
        QFrame {{
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 {PANEL}, stop:1 {PANEL_ALT});
            border: 1px solid {BORDER};
            border-left: 4px solid {accent};
            border-radius: 12px;
        }}
    """

def search_box() -> str:
    return f"""
        QLineEdit {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 10px;
            padding: 10px 14px 10px 36px;
            color: {TEXT};
            font-size: 13px;
        }}
        QLineEdit:focus {{ border-color: {ACCENT}; }}
    """
