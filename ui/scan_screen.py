"""ui/scan_screen.py — Real-time scan progress screen for DocuWise."""
from __future__ import annotations
import time
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QFrame, QSizePolicy,
)


class ScanScreen(QWidget):
    """Shown while a scan is running. Updated via update_progress()."""

    STAGES = ["Scanning Files", "Extracting Text", "AI Analysis", "Embedding", "Duplicate Detection"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._start_time: float = 0.0
        self._processed = 0
        self._total = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(80, 60, 80, 60)
        root.setSpacing(20)
        root.addStretch(1)

        # Title
        title = QLabel("Scanning…")
        tf = QFont(); tf.setPointSize(22); tf.setBold(True)
        title.setFont(tf)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #1a1a2e;")
        root.addWidget(title)

        # Stage badge
        self._stage_lbl = QLabel("Initialising")
        sf = QFont(); sf.setPointSize(12)
        self._stage_lbl.setFont(sf)
        self._stage_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stage_lbl.setStyleSheet(
            "color: #2c3e8c; background: #eef2ff; border-radius: 6px; padding: 4px 16px;"
        )
        root.addWidget(self._stage_lbl)

        # Current file
        self._file_lbl = QLabel("")
        fl = QFont(); fl.setPointSize(9)
        self._file_lbl.setFont(fl)
        self._file_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._file_lbl.setStyleSheet("color: #555;")
        self._file_lbl.setWordWrap(True)
        root.addWidget(self._file_lbl)

        # Progress bar
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setMinimumHeight(18)
        self._bar.setTextVisible(True)
        self._bar.setStyleSheet("""
            QProgressBar { border: 1px solid #ccc; border-radius: 8px; background: #f0f0f0; }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #2c3e8c, stop:1 #6c63ff); border-radius: 7px; }
        """)
        root.addWidget(self._bar)

        # Stats row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(32)

        def stat(label):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            val = QLabel("—")
            vf = QFont(); vf.setPointSize(16); vf.setBold(True)
            val.setFont(vf)
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val.setStyleSheet("color: #2c3e8c;")
            lbl = QLabel(label)
            lf = QFont(); lf.setPointSize(8)
            lbl.setFont(lf)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #888;")
            v.addWidget(val); v.addWidget(lbl)
            return w, val

        w1, self._lbl_count   = stat("Files Processed")
        w2, self._lbl_elapsed = stat("Elapsed")
        w3, self._lbl_eta     = stat("Remaining")
        w4, self._lbl_speed   = stat("Files / min")

        for w in [w1, w2, w3, w4]:
            stats_row.addWidget(w)
        root.addLayout(stats_row)
        root.addStretch(1)

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self, folder: str):
        self._start_time = time.monotonic()
        self._processed = 0
        self._total = 0
        self._bar.setValue(0)
        self._bar.setRange(0, 100)
        self._stage_lbl.setText("Scanning Files")
        self._file_lbl.setText(folder)
        self._lbl_count.setText("0")
        self._lbl_elapsed.setText("0s")
        self._lbl_eta.setText("—")
        self._lbl_speed.setText("—")
        self._timer.start(500)

    def stop(self):
        self._timer.stop()

    def update_progress(self, current: int, total: int, filename: str):
        self._processed = current
        self._total = total
        pct = int(current / total * 100) if total > 0 else 0
        self._bar.setValue(pct)
        self._bar.setFormat(f"{current} / {total}  ({pct}%)")
        self._file_lbl.setText(filename)
        self._stage_lbl.setText("Extracting · Analysing · Embedding")
        self._lbl_count.setText(f"{current} / {total}")

    def set_stage(self, stage: str):
        self._stage_lbl.setText(stage)

    # ── Internal timer ────────────────────────────────────────────────────────

    def _tick(self):
        elapsed = time.monotonic() - self._start_time
        self._lbl_elapsed.setText(_fmt_time(elapsed))
        if self._processed > 0 and self._total > 0:
            rate = self._processed / (elapsed / 60) if elapsed > 0 else 0
            self._lbl_speed.setText(f"{rate:.0f}")
            remaining = (self._total - self._processed) / (rate / 60) if rate > 0 else 0
            self._lbl_eta.setText(_fmt_time(remaining))


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    if s < 60:   return f"{s}s"
    if s < 3600: return f"{s//60}m {s%60}s"
    return f"{s//3600}h {(s%3600)//60}m"
