"""
core/analyzer.py — Provider-agnostic document analysis coordinator for DocuWise.

Responsibilities:
  - Cache check (Part 3): skip the LLM if the document was already analyzed and unchanged.
  - Delegate all LLM calls to llm_provider.get_provider() with automatic fallback.
  - Persist results + analysis_source to the database.
  - Advance processing_status to 'analyzed' on success or 'failed' on error.

This module contains ZERO provider-specific code.
To switch providers, change LLM_PROVIDER in config.py.
"""

import json as _json
import logging
import time
from typing import Optional

from config import API_CALL_DELAY_SECONDS, ENABLE_ANALYSIS_CACHE, ENABLE_FALLBACK_ANALYSIS
from core.database import _connect, update_document_analysis, update_document_status
from core.llm_provider import (
    DocumentAnalysis,
    HeuristicProvider,
    _metrics,
    get_provider,
    is_budget_exhausted,
)

# Re-export for backward compatibility with existing imports.
__all__ = ["DocumentAnalysis", "analyze_document", "analyze_text", "validate_model"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public analysis API
# ---------------------------------------------------------------------------

def analyze_text(
    text: str,
    user_rules: Optional[str] = None,
) -> DocumentAnalysis:
    """
    Analyze document text using the configured LLM provider.

    If ENABLE_FALLBACK_ANALYSIS=True (default), any provider failure
    automatically re-runs with HeuristicProvider so callers always receive
    a usable result. The heuristic result carries analysis_source='fallback'
    and confidence_score in [0.50, 0.75].

    Args:
        text:       Extracted plain-text content of the document.
        user_rules: Optional natural-language rule string (future rules engine).

    Returns:
        DocumentAnalysis. success is True after fallback.
    """
    if not text or not text.strip():
        return DocumentAnalysis(success=False, error_message="Cannot analyze empty text.")

    # Budget gate — if scan budget exhausted, fall through to heuristic
    if is_budget_exhausted():
        if ENABLE_FALLBACK_ANALYSIS:
            logger.info("Scan budget exhausted — using HeuristicProvider.")
            return HeuristicProvider().analyze(text, user_rules)
        return DocumentAnalysis(
            success=False,
            error_message="LLM request budget exhausted for this scan.",
        )

    provider = get_provider()
    result = provider.analyze(text, user_rules)

    if not result.success and ENABLE_FALLBACK_ANALYSIS:
        primary = type(provider).__name__
        logger.warning(
            "%s failed — falling back to HeuristicProvider. Reason: %s",
            primary, result.error_message,
        )
        result = HeuristicProvider().analyze(text, user_rules)
        result.error_message = f"[Heuristic fallback — {primary} unavailable]"

    return result


def validate_model() -> bool:
    """
    Verify that a real LLM provider (NVIDIA or Gemini) is active.

    Returns True for NVIDIA/Gemini, False if only HeuristicProvider is available.
    """
    try:
        provider = get_provider()
        is_real = not isinstance(provider, HeuristicProvider)
        logger.info(
            "LLM provider: %s (%s)",
            type(provider).__name__,
            "LLM" if is_real else "heuristic fallback only",
        )
        return is_real
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM provider validation failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------

def analyze_document(
    file_path: str,
    user_rules: Optional[str] = None,
) -> DocumentAnalysis:
    """
    Full analysis workflow for a single document.

    Steps:
      1. Load the document record from the database.
      2. Part 3 — Cache check: if already analyzed and file unchanged, return cached.
      3. Call analyze_text() → provider with automatic heuristic fallback.
      4. Persist results via update_document_analysis() including analysis_source.
      5. Advance processing_status to 'analyzed'.

    Args:
        file_path:  Absolute path to the document (primary DB key).
        user_rules: Optional active rule string for future rules engine.

    Returns:
        DocumentAnalysis. Inspect .success and .error_message for details.
    """
    doc = _get_document(file_path)
    if doc is None:
        msg = f"Document not found in DB: '{file_path}'"
        logger.error(msg)
        return DocumentAnalysis(success=False, error_message=msg)

    # ── Part 3 — Cache check ───────────────────────────────────────────────
    if ENABLE_ANALYSIS_CACHE and _is_cache_valid(doc):
        logger.info("CACHE HIT - skipped NVIDIA request for '%s'", doc.get("filename"))
        _metrics["documents_cached"] += 1
        _metrics["api_calls_saved"] += 1
        return _build_from_cache(doc)

    # ── Extract text ───────────────────────────────────────────────────────
    extracted_text: Optional[str] = doc.get("extracted_text")
    if not extracted_text or not extracted_text.strip():
        msg = f"No extracted text for '{file_path}'. Run extractor first."
        logger.warning(msg)
        update_document_status(file_path, "failed", error_message=msg)
        return DocumentAnalysis(success=False, error_message=msg)

    # ── Analyse ────────────────────────────────────────────────────────────
    logger.info("Analyzing: '%s'", file_path)
    time.sleep(API_CALL_DELAY_SECONDS)
    analysis = analyze_text(extracted_text, user_rules)

    if not analysis.success:
        update_document_status(file_path, "failed", error_message=analysis.error_message)
        return analysis

    # ── Persist ────────────────────────────────────────────────────────────
    try:
        update_document_analysis(
            file_path=file_path,
            summary=analysis.summary,
            category=analysis.category,
            subject=analysis.subject,
            tags_json=_json.dumps(analysis.tags),
            importance_score=analysis.importance_score,
            highlight=0,
            highlight_reason=None,
            deletion_candidate=1 if analysis.deletion_candidate else 0,
            deletion_reason=analysis.deletion_reason or None,
            analysis_source=analysis.analysis_source,
        )
        logger.info(
            "Analyzed '%s' | source=%s | category='%s' | importance=%d",
            file_path, analysis.analysis_source, analysis.category, analysis.importance_score,
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"DB write failed after analysis: {exc}"
        logger.error("DB write failed for '%s': %s", file_path, exc, exc_info=True)
        analysis.success = False
        analysis.error_message = msg
        update_document_status(file_path, "failed", error_message=msg)

    return analysis


# ---------------------------------------------------------------------------
# Cache helpers (Part 3)
# ---------------------------------------------------------------------------

def _is_cache_valid(doc: dict) -> bool:
    """
    Return True if the document has a complete, up-to-date analysis in the DB.

    A cache hit requires ALL of:
      - processing_status is 'analyzed', 'embedded', or 'completed'
      - summary is non-empty
      - category is set
      - subject is set
    The md5_hash guarantee is handled upstream: the scanner resets status to
    'pending' whenever the file's md5_hash changes, so by the time we reach
    analyze_document() the hash is implicitly still valid.
    """
    return (
        doc.get("processing_status") in ("analyzed", "embedded", "completed")
        and bool(doc.get("summary", "").strip())
        and bool(doc.get("category", "").strip())
        and bool(doc.get("subject", "").strip())
    )


def _build_from_cache(doc: dict) -> DocumentAnalysis:
    """Reconstruct a DocumentAnalysis from an already-analyzed DB row."""
    tags_raw = doc.get("tags_json") or "[]"
    try:
        tags = _json.loads(tags_raw)
    except Exception:  # noqa: BLE001
        tags = []

    return DocumentAnalysis(
        summary=doc.get("summary") or "",
        category=doc.get("category") or "Miscellaneous",
        subject=doc.get("subject") or "",
        tags=tags,
        importance_score=int(doc.get("importance_score") or 5),
        deletion_candidate=bool(doc.get("deletion_candidate")),
        deletion_reason=doc.get("deletion_reason") or "",
        confidence_score=1.0,        # perfect confidence — came from DB
        analysis_source="cached",
        success=True,
    )


# ---------------------------------------------------------------------------
# Internal DB helper
# ---------------------------------------------------------------------------

def _get_document(file_path: str) -> Optional[dict]:
    """Retrieve a single document record from the database by file_path."""
    try:
        conn = _connect()
        with conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE file_path = ? LIMIT 1",
                (file_path,),
            ).fetchone()
        return dict(row) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.error("DB lookup failed for '%s': %s", file_path, exc)
        return None
