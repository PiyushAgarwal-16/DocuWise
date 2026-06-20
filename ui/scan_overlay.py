"""ui/scan_overlay.py — Real-time scan progress overlay for DocuWise."""
from __future__ import annotations
import time
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QProgressBar, QSizePolicy,
)
from ui import styles as S


class ScanOverlay(QWidget):
    """
    Full-screen overlay that appears during scanning.
    Shows real-time progress metrics including file name, stage,
    progress bar, elapsed time, ETA, and throughput.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._start_time: float = 0
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._current = 0
        self._total = 0

        self.setStyleSheet(f"background: {S.BG};")
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.setContentsMargins(60, 40, 60, 40)

        # Center card
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {S.PANEL};
                border: 1px solid {S.BORDER};
                border-radius: 16px;
            }}
        """)
        card.setMaximumWidth(640)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(40, 32, 40, 32)
        card_lay.setSpacing(20)

        # Scanning animation label
        self._icon = QLabel("⚡")
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet(f"font-size: 36px; border: none;")
        card_lay.addWidget(self._icon)

        self._title = QLabel("Scanning...")
        tf = QFont(); tf.setPointSize(20); tf.setBold(True)
        self._title.setFont(tf)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet(f"color: {S.TEXT}; border: none;")
        card_lay.addWidget(self._title)

        self._folder_lbl = QLabel("")
        self._folder_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._folder_lbl.setStyleSheet(f"color: {S.MUTED}; font-size: 12px; border: none;")
        self._folder_lbl.setWordWrap(True)
        card_lay.addWidget(self._folder_lbl)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setMinimumHeight(12)
        self._progress.setTextVisible(False)
        card_lay.addWidget(self._progress)

        # Status row
        self._status = QLabel("Preparing...")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(f"color: {S.ACCENT}; font-size: 13px; border: none;")
        self._status.setWordWrap(True)
        card_lay.addWidget(self._status)

        # Metrics grid
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(24)

        self._m_progress = self._metric("Progress", "—")
        self._m_elapsed  = self._metric("Elapsed", "0:00")
        self._m_eta      = self._metric("ETA", "—")
        self._m_speed    = self._metric("Speed", "—")

        for w in [self._m_progress, self._m_elapsed, self._m_eta, self._m_speed]:
            metrics_row.addWidget(w)

        card_lay.addLayout(metrics_row)

        # Current file
        self._file_lbl = QLabel("")
        self._file_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._file_lbl.setStyleSheet(f"color: {S.MUTED_DIM}; font-size: 11px; border: none;")
        self._file_lbl.setWordWrap(True)
        card_lay.addWidget(self._file_lbl)

        root.addStretch()
        root.addWidget(card)
        root.addStretch()

    def _metric(self, label: str, initial: str) -> QFrame:
        f = QFrame()
        f.setStyleSheet(f"background: {S.SURFACE}; border-radius: 8px; border: none;")
        l = QVBoxLayout(f)
        l.setContentsMargins(14, 10, 14, 10)
        l.setSpacing(2)
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)

        val = QLabel(initial)
        vf = QFont(); vf.setPointSize(16); vf.setBold(True)
        val.setFont(vf)
        val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val.setStyleSheet(f"color: {S.TEXT}; border: none;")
        val.setObjectName("val")

        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"color: {S.MUTED}; font-size: 10px; border: none;")

        l.addWidget(val)
        l.addWidget(lbl)
        return f

    def _set_metric(self, frame: QFrame, text: str):
        val = frame.findChild(QLabel, "val")
        if val:
            val.setText(text)

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self, folder: str):
        self._start_time = time.monotonic()
        self._current = 0
        self._total = 0
        self._folder_lbl.setText(f"📁  {folder}")
        self._status.setText("Scanning filesystem...")
        self._progress.setRange(0, 0)  # indeterminate
        self._file_lbl.setText("")
        self._set_metric(self._m_progress, "—")
        self._set_metric(self._m_elapsed, "0:00")
        self._set_metric(self._m_eta, "—")
        self._set_metric(self._m_speed, "—")
        self._timer.start()

    def update_progress(self, current: int, total: int, filename: str):
        self._current = current
        self._total = total

        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(current)

        pct = int(current / total * 100) if total > 0 else 0
        self._set_metric(self._m_progress, f"{current}/{total}")
        self._title.setText(f"Processing... {pct}%")

        # Detect stage from filename pattern
        if "[cache hit" in filename.lower():
            stage = "💾 Cache Hit"
        else:
            stage = "📄 Processing"

        self._status.setText(stage)
        # Show just the base filename
        display = filename.split("[")[0].strip() if "[" in filename else filename
        self._file_lbl.setText(display)
        self._tick()

    def stop(self):
        self._timer.stop()
        elapsed = time.monotonic() - self._start_time
        self._title.setText("Scan Complete ✓")
        self._status.setText(f"Finished in {self._fmt_time(elapsed)}")
        self._progress.setValue(self._progress.maximum() or 1)

    def _tick(self):
        elapsed = time.monotonic() - self._start_time
        self._set_metric(self._m_elapsed, self._fmt_time(elapsed))

        if self._current > 0 and self._total > 0:
            rate = self._current / elapsed if elapsed > 0 else 0
            remaining = self._total - self._current
            eta = remaining / rate if rate > 0 else 0
            self._set_metric(self._m_eta, self._fmt_time(eta))
            self._set_metric(self._m_speed, f"{rate*60:.0f}/min")

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
