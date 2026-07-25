"""
core/content_cache.py — Reusable Content Cache service for DocuWise (Phase 2).

The Content Cache guarantees that every expensive operation — OCR, NVIDIA
analysis, and embedding generation — happens **at most once per unique document
content**, keyed by the MD5 of the raw file bytes. Moved, copied, renamed, or
byte-identical duplicate files reuse the cached results instantly.

This module is the single home for cache *policy* (what counts as a hit, what to
reuse, how to backfill). All raw SQL lives in ``core.database`` — this service
only orchestrates those primitives, keeping the data-access layer free of
business logic (SRP).

Two flavours of cache hit
-------------------------
  * **Complete hit** — the entry already holds final text + embedding + analysis.
    The document is restored wholesale and skips OCR, NVIDIA, and embedding.
  * **Text hit** — the entry holds final/OCR text but no analysis yet. The
    extractor reuses the text (so OCR never re-runs) but the document still flows
    through analysis + embedding, which then finalise the entry.

Backward compatibility
-----------------------
Documents processed before this cache existed live only in the ``documents``
table. :func:`lookup` therefore falls back to an MD5 match against ``documents``
and, on a hit, backfills ``content_cache`` so the fast path is used thereafter.
This subsumes the pipeline's former ad-hoc MD5 cache — there is now exactly one
caching mechanism.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from config import CONTENT_CACHE_ENABLED
from core import database as db
from core.logging_events import log_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hit classification
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    """Return True if the content cache is globally enabled via config."""
    return bool(CONTENT_CACHE_ENABLED)


def has_text(entry: Optional[dict]) -> bool:
    """True if *entry* carries usable final text (so OCR need not re-run)."""
    if not entry:
        return False
    return bool((entry.get("final_text") or "").strip())


def is_complete(entry: Optional[dict]) -> bool:
    """
    True if *entry* holds everything needed to skip OCR, NVIDIA, and embedding.

    Requires final text, an embedding vector, and a summary — the three
    artefacts of the three expensive stages.
    """
    if not entry:
        return False
    return (
        bool((entry.get("final_text") or "").strip())
        and bool((entry.get("embedding_json") or "").strip())
        and bool((entry.get("summary") or "").strip())
    )


# ---------------------------------------------------------------------------
# Lookup (with documents-MD5 backward-compat fallback)
# ---------------------------------------------------------------------------

def lookup(md5_hash: str, exclude_file_path: str = "", filename: str = "") -> Optional[dict]:
    """
    Return the content_cache entry for *md5_hash*, or None on a miss.

    On a native cache miss, falls back to a fully-processed sibling in the
    ``documents`` table (same MD5, different path). When such a sibling exists
    its data is adapted into a cache-entry dict **and** written into
    ``content_cache`` (backfill), so subsequent lookups take the fast path.

    Args:
        md5_hash:          Content hash to look up.
        exclude_file_path: Path of the document currently being processed, so a
                           documents-fallback never matches the file itself.
        filename:          Bare filename, used only for structured logging.

    Returns:
        A cache-entry dict, or None.
    """
    if not is_enabled() or not md5_hash:
        return None

    entry = db.content_cache_get(md5_hash)
    if entry is not None:
        log_event(logger, "CONTENT_CACHE_HIT", file=filename, md5=md5_hash,
                  kind=("complete" if is_complete(entry) else "text"))
        return entry

    # Fallback: a pre-cache document with identical content.
    sibling = db.find_by_md5(md5_hash, exclude_file_path=exclude_file_path)
    if sibling is not None:
        adapted = _entry_from_document(sibling)
        _backfill(md5_hash, adapted)
        log_event(logger, "CONTENT_CACHE_HIT", file=filename, md5=md5_hash,
                  kind="backfill", source=sibling.get("filename"))
        return adapted

    log_event(logger, "CONTENT_CACHE_MISS", file=filename, md5=md5_hash)
    return None


def _entry_from_document(doc: dict) -> dict:
    """Adapt a ``documents`` row into the content_cache entry shape."""
    return {
        "final_text": doc.get("extracted_text") or "",
        "native_text": doc.get("extracted_text") or "",
        "ocr_text": None,
        "extraction_method": doc.get("extraction_method"),
        "embedding_json": doc.get("embedding_json"),
        "summary": doc.get("summary"),
        "category": doc.get("category"),
        "subject": doc.get("subject"),
        "tags_json": doc.get("tags_json"),
        "importance_score": doc.get("importance_score"),
        "analysis_source": doc.get("analysis_source"),
        "ocr_engine": doc.get("ocr_engine"),
        "ocr_version": doc.get("ocr_version"),
        "ocr_confidence": doc.get("ocr_confidence"),
        "ocr_pages_processed": doc.get("ocr_pages_processed"),
        "ocr_processing_time_ms": doc.get("ocr_processing_time_ms"),
        # Restore-only extras (not stored in content_cache, but honoured by
        # restore_document_from_cache when present on the dict).
        "deletion_candidate": doc.get("deletion_candidate"),
        "deletion_reason": doc.get("deletion_reason"),
        "highlight": doc.get("highlight"),
        "highlight_reason": doc.get("highlight_reason"),
    }


def _backfill(md5_hash: str, entry: dict) -> None:
    """Persist an adapted documents-row entry into content_cache (best effort)."""
    try:
        db.content_cache_upsert(
            md5_hash,
            native_text=entry.get("native_text"),
            final_text=entry.get("final_text"),
            extraction_method=entry.get("extraction_method"),
            embedding_json=entry.get("embedding_json"),
            summary=entry.get("summary"),
            category=entry.get("category"),
            subject=entry.get("subject"),
            tags_json=entry.get("tags_json"),
            importance_score=entry.get("importance_score"),
            analysis_source=entry.get("analysis_source"),
            ocr_engine=entry.get("ocr_engine"),
            ocr_version=entry.get("ocr_version"),
            ocr_confidence=entry.get("ocr_confidence"),
            ocr_pages_processed=entry.get("ocr_pages_processed"),
            ocr_processing_time_ms=entry.get("ocr_processing_time_ms"),
        )
    except Exception as exc:  # noqa: BLE001 — backfill is an optimisation, never fatal
        logger.debug("content_cache backfill skipped for %s: %s", md5_hash[:8], exc)


# ---------------------------------------------------------------------------
# Restore (cache → document)
# ---------------------------------------------------------------------------

def restore_to_document(file_path: str, entry: dict) -> None:
    """
    Restore a complete cache *entry* into the document at *file_path*.

    Sets the document to 'embedded' with analysis_source='cached'. The caller is
    responsible for having verified :func:`is_complete` first.
    """
    db.restore_document_from_cache(file_path, entry)


# ---------------------------------------------------------------------------
# Seed (extraction → cache) and finalise (analysis+embedding → cache)
# ---------------------------------------------------------------------------

def seed_text(
    md5_hash: str,
    *,
    native_text: str,
    ocr_text: Optional[str],
    final_text: str,
    extraction_method: str,
    ocr_engine: Optional[str] = None,
    ocr_version: Optional[str] = None,
    ocr_confidence: Optional[float] = None,
    ocr_pages_processed: int = 0,
    ocr_processing_time_ms: int = 0,
) -> None:
    """
    Store the text layers of a freshly extracted document (a partial entry).

    Called by the extractor on a cache miss so that even if analysis or embedding
    later fail, the (expensive) OCR text is never lost or recomputed.
    """
    if not is_enabled() or not md5_hash:
        return
    try:
        db.content_cache_upsert(
            md5_hash,
            native_text=native_text,
            ocr_text=ocr_text,
            final_text=final_text,
            extraction_method=extraction_method,
            ocr_engine=ocr_engine,
            ocr_version=ocr_version,
            ocr_confidence=ocr_confidence,
            ocr_pages_processed=ocr_pages_processed,
            ocr_processing_time_ms=ocr_processing_time_ms,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("content_cache seed failed for %s: %s", md5_hash[:8], exc)


def store_from_document(file_path: str) -> None:
    """
    Finalise the cache entry for a document that just completed analysis+embedding.

    Reads the now-complete ``documents`` row and upserts its embedding + analysis
    into ``content_cache`` (text layers seeded earlier are preserved via the
    COALESCE-based upsert). After this call the content is a complete cache hit
    for any future identical file.
    """
    if not is_enabled():
        return

    doc = db.get_document(file_path)
    if doc is None or not doc.get("md5_hash"):
        return

    try:
        db.content_cache_upsert(
            doc["md5_hash"],
            final_text=doc.get("extracted_text"),
            extraction_method=doc.get("extraction_method"),
            embedding_json=doc.get("embedding_json"),
            summary=doc.get("summary"),
            category=doc.get("category"),
            subject=doc.get("subject"),
            tags_json=doc.get("tags_json"),
            importance_score=doc.get("importance_score"),
            analysis_source=doc.get("analysis_source"),
            ocr_engine=doc.get("ocr_engine"),
            ocr_version=doc.get("ocr_version"),
            ocr_confidence=doc.get("ocr_confidence"),
            ocr_pages_processed=doc.get("ocr_pages_processed"),
            ocr_processing_time_ms=doc.get("ocr_processing_time_ms"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("content_cache finalise failed for '%s': %s", file_path, exc)


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def parse_tags(entry: dict) -> list[str]:
    """Best-effort parse of the entry's tags_json into a list of strings."""
    raw = entry.get("tags_json") or "[]"
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:  # noqa: BLE001
        return []
