"""
core/logging_events.py — Structured event logging for DocuWise (Phase 13).

A single tiny helper so every module emits pipeline events in one consistent,
machine-greppable shape::

    CONTENT_CACHE_HIT | file=report.pdf md5=a1b2c3d4 pages=3

The event token is always the first thing on the line, which lets the SSE log
handler in api_server.py map events to live-scan stages, and lets operators
grep logs for a specific event (OCR_FAILED, NVIDIA_SKIPPED_CACHE, …).

Canonical event tokens (Phase 13):
    CONTENT_CACHE_HIT / CONTENT_CACHE_MISS
    OCR_STARTED / OCR_PAGE_SKIPPED / OCR_PAGE_COMPLETED / OCR_COMPLETED / OCR_FAILED
    NVIDIA_SKIPPED_CACHE / EMBEDDING_SKIPPED_CACHE
"""

from __future__ import annotations

import logging
from typing import Any


def log_event(
    logger: logging.Logger,
    event: str,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """
    Emit a single structured event line.

    Args:
        logger: The calling module's logger.
        event:  Event token (e.g. "OCR_COMPLETED"). Placed first on the line.
        level:  Logging level (default INFO).
        **fields: Arbitrary key/value context (filename, md5, page, duration…).
                  ``None`` values are omitted. An ``md5`` value is shortened to
                  its first 8 characters for readability.
    """
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        if key == "md5" and isinstance(value, str) and len(value) > 8:
            value = value[:8]
        parts.append(f"{key}={value}")

    suffix = (" | " + " ".join(parts)) if parts else ""
    logger.log(level, "%s%s", event, suffix)
