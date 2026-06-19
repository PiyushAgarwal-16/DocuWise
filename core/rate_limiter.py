"""
core/rate_limiter.py — SQLite-backed rate limiter for LLM API calls.

Responsibilities:
  - Record every outgoing API call with a timestamp in the database.
  - Enforce per-minute and per-hour request ceilings before each call.
  - Sleep automatically when a ceiling is reached (no exceptions thrown).
  - Survive application restarts — history persists in the main SQLite DB.
  - Clean up stale log entries older than a configurable retention window.

Usage:
    from core.rate_limiter import check_and_wait, record_request

    check_and_wait("nvidia")          # blocks if near limit
    # ... make API call ...
    record_request("nvidia")          # persist after successful call
"""

import logging
import os
import sqlite3
import time
from datetime import datetime, timezone

from config import (
    DB_PATH,
    NVIDIA_MAX_REQUESTS_PER_HOUR,
    NVIDIA_MAX_REQUESTS_PER_MINUTE,
    NVIDIA_REQUEST_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)

# ── Retention ──────────────────────────────────────────────────────────────────
_LOG_RETENTION_DAYS = 3  # purge entries older than this on cleanup


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    """Open the main DocuWise SQLite database (WAL mode)."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def ensure_table() -> None:
    """
    Create the rate_limit_log table if it doesn't already exist.

    Called lazily on first use — safe to call multiple times.
    """
    conn = _connect()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rate_limit_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                provider  TEXT    NOT NULL,
                timestamp TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_rate_limit_provider_ts
                ON rate_limit_log (provider, timestamp)
        """)


# ---------------------------------------------------------------------------
# Core public API
# ---------------------------------------------------------------------------

def record_request(provider: str) -> None:
    """
    Persist a record of one outgoing API call.

    Call this AFTER a successful API request to keep the usage history
    accurate across restarts.

    Args:
        provider: Provider identifier string, e.g. 'nvidia'.
    """
    ensure_table()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = _connect()
        with conn:
            conn.execute(
                "INSERT INTO rate_limit_log (provider, timestamp) VALUES (?, ?)",
                (provider, now),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("rate_limiter: failed to record request: %s", exc)


def get_recent_count(provider: str, window_seconds: int) -> int:
    """
    Count recorded requests for *provider* within the last *window_seconds*.

    Args:
        provider:       Provider identifier string.
        window_seconds: Look-back window in seconds (e.g. 60 for per-minute).

    Returns:
        Number of requests in the window. 0 on any DB error.
    """
    ensure_table()
    cutoff = datetime.fromtimestamp(
        time.time() - window_seconds, tz=timezone.utc
    ).isoformat()
    try:
        conn = _connect()
        with conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM rate_limit_log WHERE provider = ? AND timestamp >= ?",
                (provider, cutoff),
            ).fetchone()
        return row[0] if row else 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("rate_limiter: count query failed: %s", exc)
        return 0


def check_and_wait(provider: str = "nvidia") -> int:
    """
    Enforce rate limits before an outgoing API call.

    Checks both the per-minute and per-hour ceilings. If either is
    exceeded, sleeps in increments until the window clears, then applies
    the mandatory inter-request delay (NVIDIA_REQUEST_DELAY_SECONDS).

    This function BLOCKS the calling thread — it never raises an exception.

    Args:
        provider: Provider identifier string (default 'nvidia').

    Returns:
        Total seconds slept (useful for metrics / logging).
    """
    total_slept = 0

    # ── Per-minute check ───────────────────────────────────────────────────
    while True:
        last_minute = get_recent_count(provider, 60)
        if last_minute < NVIDIA_MAX_REQUESTS_PER_MINUTE:
            break
        sleep_for = 10
        logger.warning(
            "Rate limit — %d/%d requests/min for '%s'. Sleeping %ds...",
            last_minute, NVIDIA_MAX_REQUESTS_PER_MINUTE, provider, sleep_for,
        )
        time.sleep(sleep_for)
        total_slept += sleep_for

    # ── Per-hour check ─────────────────────────────────────────────────────
    while True:
        last_hour = get_recent_count(provider, 3600)
        if last_hour < NVIDIA_MAX_REQUESTS_PER_HOUR:
            break
        sleep_for = 60
        logger.warning(
            "Rate limit — %d/%d requests/hour for '%s'. Sleeping %ds...",
            last_hour, NVIDIA_MAX_REQUESTS_PER_HOUR, provider, sleep_for,
        )
        time.sleep(sleep_for)
        total_slept += sleep_for

    # ── Mandatory inter-request delay ──────────────────────────────────────
    if NVIDIA_REQUEST_DELAY_SECONDS > 0:
        time.sleep(NVIDIA_REQUEST_DELAY_SECONDS)
        total_slept += NVIDIA_REQUEST_DELAY_SECONDS

    return int(total_slept)


def cleanup_old_logs(days: int = _LOG_RETENTION_DAYS) -> int:
    """
    Delete rate_limit_log rows older than *days* days.

    Safe to call from a maintenance routine or at scan start.

    Returns:
        Number of rows deleted.
    """
    ensure_table()
    cutoff = datetime.fromtimestamp(
        time.time() - days * 86_400, tz=timezone.utc
    ).isoformat()
    try:
        conn = _connect()
        with conn:
            cursor = conn.execute(
                "DELETE FROM rate_limit_log WHERE timestamp < ?",
                (cutoff,),
            )
        deleted = cursor.rowcount
        if deleted:
            logger.debug("rate_limiter: purged %d stale log entries (>%d days).", deleted, days)
        return deleted
    except Exception as exc:  # noqa: BLE001
        logger.warning("rate_limiter: cleanup failed: %s", exc)
        return 0


def get_usage_summary(provider: str = "nvidia") -> dict:
    """
    Return a summary of recent API usage for display in the UI.

    Returns:
        Dict with keys: last_minute, last_hour, limit_per_minute, limit_per_hour.
    """
    return {
        "last_minute":       get_recent_count(provider, 60),
        "last_hour":         get_recent_count(provider, 3600),
        "limit_per_minute":  NVIDIA_MAX_REQUESTS_PER_MINUTE,
        "limit_per_hour":    NVIDIA_MAX_REQUESTS_PER_HOUR,
        "provider":          provider,
    }
