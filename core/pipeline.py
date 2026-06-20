"""
core/pipeline.py — Processing pipeline orchestrator for DocuWise.

Responsibilities:
  - Coordinate the full document processing workflow across all core modules.
  - Drive each document through: Extract → Analyze → Embed.
  - Continue processing if any single document fails.
  - Detect duplicates across the full embedded corpus after processing.
  - Expose run_full_scan() as the single entry point for the UI layer.

This module does NOT:
  - Implement any extraction, analysis, or embedding logic directly.
  - Touch SQLite directly — all DB access goes through database.py.
  - Interact with the UI.
"""

import logging
import os
import time
from typing import Optional

from core.analyzer import analyze_document
from core.database import (
    _connect,
    cleanup_missing_files,
    copy_analysis_from_cache,
    find_by_md5,
    get_documents_by_status,
    init_db,
    update_document_status,
)
from core.embedder import detect_duplicates, embed_document
from core.extractor import process_document
from core.scanner import scan_folder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 1: Process all pending documents
# ---------------------------------------------------------------------------

def process_pending_documents(
    progress_callback: Optional[callable] = None,
) -> dict:
    """
    Drive every 'pending' document through the full three-stage pipeline.

    Pipeline stages per document:
      1. Extract  — process_document()  → sets status to 'extracted' or 'failed'
      2. Analyze  — analyze_document()  → sets status to 'analyzed'  or 'failed'
      3. Embed    — embed_document()    → sets status to 'embedded'  or 'failed'

    Processing continues even when individual documents fail — failures are
    counted and logged but never abort the batch. Each stage reads the status
    written by the previous stage, so a document that fails at extraction is
    automatically skipped by the analyzer and embedder (they check for
    extracted_text / processing_status preconditions internally).

    Args:
        progress_callback: Optional callable invoked after each document
                           completes all three stages. Signature:
                               callback(current: int, total: int, filename: str)
                           Useful for driving a UI progress bar without
                           coupling the pipeline to any specific UI framework.

    Returns:
        Summary dict:
        {
            "processed": int,   # documents that completed all 3 stages
            "failed":    int,   # documents that failed at any stage
            "skipped":   int,   # documents with no extractable text (low word count, etc.)
        }
    """
    pending = get_documents_by_status("pending") + get_documents_by_status("extracted")
    # De-duplicate in case a doc appears in both (shouldn't happen, but defensive)
    seen: set = set()
    unique_pending = []
    for d in pending:
        if d["file_path"] not in seen:
            seen.add(d["file_path"])
            unique_pending.append(d)
    pending = unique_pending
    total = len(pending)

    if total == 0:
        logger.info("No pending/extracted documents — pipeline has nothing to do.")
        return {"processed": 0, "failed": 0, "skipped": 0, "image_only": 0}

    logger.info("Pipeline starting — %d pending document(s) to process.", total)
    counters = {"processed": 0, "failed": 0, "skipped": 0, "image_only": 0,
                "cache_hits": 0, "cache_misses": 0}

    for index, doc in enumerate(pending, start=1):
        file_path: str = doc["file_path"]
        filename: str = doc.get("filename", file_path)

        logger.info("[%d/%d] Processing: '%s'", index, total, filename)

        # ── Missing-file guard (Task 8) ──────────────────────────────────────
        # If the file was deleted between the scan and pipeline stages, mark
        # it as 'missing' and skip ALL processing stages immediately.
        if not os.path.exists(file_path):
            logger.warning(
                "[MISSING] '%s' not found on disk — skipping all stages.", filename
            )
            update_document_status(file_path, "missing")
            counters["failed"] += 1
            _report_progress(progress_callback, index, total, filename)
            continue

        doc_failed = False
        doc_skipped = False

        # ── Stage 1: Extract ─────────────────────────────────────────────────
        try:
            extraction = process_document(file_path)
            if not extraction.success:
                logger.warning("Extract FAILED for '%s': %s", filename, extraction.error_message)
                doc_failed = True
            elif extraction.image_only:
                # Image-based PDF: extraction succeeded but no text was found.
                # Skip Gemini analysis and embedding — this is not a failure.
                logger.info("Image-only PDF skipped (no OCR): '%s'", filename)
                counters["image_only"] += 1
                _report_progress(progress_callback, index, total, filename)
                continue
        except Exception as exc:  # noqa: BLE001
            logger.error("Extract raised exception for '%s': %s", filename, exc, exc_info=True)
            doc_failed = True

        if doc_failed:
            counters["failed"] += 1
            _report_progress(progress_callback, index, total, filename)
            continue

        # ── Stage 1b: MD5 Content Cache ──────────────────────────────────────
        # After extraction the md5_hash is stored in the DB. Check if another
        # document with the same hash was already fully processed. If so, copy
        # its analysis + embedding directly — no LLM or embedder call needed.
        try:
            conn = _connect()
            md5_row = conn.execute(
                "SELECT md5_hash FROM documents WHERE file_path = ? LIMIT 1",
                (file_path,),
            ).fetchone()
            conn.close()
            current_md5 = md5_row["md5_hash"] if md5_row else None
        except Exception:
            current_md5 = None

        if current_md5:
            cache_source = find_by_md5(current_md5, exclude_file_path=file_path)
            if cache_source:
                src_name = cache_source.get("filename", "unknown")
                logger.info(
                    "[CACHE HIT] '%s' ← '%s' (md5=%s…)",
                    filename, src_name, current_md5[:8],
                )
                _report_progress(progress_callback, index, total,
                                 f"{filename}  [cache hit ← {src_name}]")
                copy_analysis_from_cache(file_path, cache_source)
                counters["cache_hits"]  += 1
                counters["processed"]   += 1
                continue   # skip Stage 2 (Analyze) and Stage 3 (Embed)

        counters["cache_misses"] += 1
        try:
            analysis = analyze_document(file_path)
            if not analysis.success:
                logger.warning("Analyze FAILED for '%s': %s", filename, analysis.error_message)
                doc_failed = True
        except Exception as exc:  # noqa: BLE001
            logger.error("Analyze raised exception for '%s': %s", filename, exc, exc_info=True)
            doc_failed = True

        if doc_failed:
            counters["failed"] += 1
            _report_progress(progress_callback, index, total, filename)
            continue

        # ── Stage 3: Embed ───────────────────────────────────────────────────
        try:
            embedded = embed_document(file_path)
            if not embedded:
                logger.warning("Embed FAILED for '%s'.", filename)
                doc_failed = True
        except Exception as exc:  # noqa: BLE001
            logger.error("Embed raised exception for '%s': %s", filename, exc, exc_info=True)
            doc_failed = True

        if doc_failed:
            counters["failed"] += 1
        else:
            counters["processed"] += 1
            logger.info("Completed '%s' ✓", filename)

        _report_progress(progress_callback, index, total, filename)

    logger.info(
        "Pipeline complete — processed=%d  failed=%d  image_only=%d  skipped=%d"
        "  cache_hits=%d  cache_misses=%d",
        counters["processed"], counters["failed"], counters["image_only"],
        counters["skipped"], counters["cache_hits"], counters["cache_misses"],
    )
    return counters


# ---------------------------------------------------------------------------
# Rescue: fix documents whose status doesn't match their actual DB state
# ---------------------------------------------------------------------------

def rescue_stalled_documents() -> dict:
    """
    Correct processing_status for documents that are stuck mid-pipeline.

    Two recovery cases handled:

    CASE A — has embedding_json BUT status='failed'
      Root cause: update_document_embedding() was called successfully but a
      subsequent operation (or a prior bug) reset the status to 'failed'.
      Fix: advance status to 'embedded' — no new work needed, data is intact.

    CASE B — has category (analysis done) BUT no embedding_json AND status='failed'
      Root cause: embedding stage crashed or was interrupted after analysis
      succeeded. The document was left at 'failed' with full analysis data.
      Fix: re-run embed_document() only — skip extraction and analysis.

    Returns:
        {"case_a_fixed": int, "case_b_embedded": int, "case_b_failed": int}
    """
    conn = _connect()

    # CASE A: has embedding but wrong status — just correct it
    case_a_rows = conn.execute("""
        SELECT file_path, filename FROM documents
        WHERE embedding_json IS NOT NULL
          AND processing_status = 'failed'
    """).fetchall()

    case_a_fixed = 0
    for row in case_a_rows:
        fp, fn = row["file_path"], row["filename"]
        try:
            update_document_status(fp, "embedded")
            logger.info("[RESCUE-A] Status corrected to 'embedded' for '%s'", fn)
            case_a_fixed += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("[RESCUE-A] Failed to correct status for '%s': %s", fn, exc)

    # CASE B: analysis done, no embedding — re-run embedding stage
    case_b_rows = conn.execute("""
        SELECT file_path, filename FROM documents
        WHERE category IS NOT NULL
          AND embedding_json IS NULL
          AND processing_status = 'failed'
    """).fetchall()

    case_b_embedded = 0
    case_b_failed = 0
    for row in case_b_rows:
        fp, fn = row["file_path"], row["filename"]
        logger.info("[RESCUE-B] Re-embedding previously analyzed doc: '%s'", fn)
        try:
            ok = embed_document(fp)
            if ok:
                case_b_embedded += 1
                logger.info("[RESCUE-B] Successfully embedded '%s'", fn)
            else:
                case_b_failed += 1
                logger.warning("[RESCUE-B] Embedding still failing for '%s'", fn)
        except Exception as exc:  # noqa: BLE001
            logger.error("[RESCUE-B] Exception embedding '%s': %s", fn, exc)
            case_b_failed += 1

    total = case_a_fixed + case_b_embedded
    if total:
        logger.info(
            "Rescue complete — case_a=%d corrected, case_b=%d embedded, case_b_failed=%d",
            case_a_fixed, case_b_embedded, case_b_failed,
        )
    else:
        logger.debug("No stalled documents found that need rescue.")

    # CASE C: failed with extracted_text but no analysis — re-queue for full pipeline
    # These failed at the analysis stage. Resetting to 'pending' gives them a new
    # pipeline pass including LLM analysis and embedding.
    case_c_rows = conn.execute("""
        SELECT file_path, filename FROM documents
        WHERE processing_status = 'failed'
          AND extracted_text IS NOT NULL
          AND category IS NULL
          AND embedding_json IS NULL
    """).fetchall()

    case_c_requeued = 0
    for row in case_c_rows:
        fp, fn = row["file_path"], row["filename"]
        try:
            update_document_status(fp, "extracted")  # Resume from analysis stage
            logger.info("[RESCUE-C] Reset to 'extracted' for re-analysis: '%s'", fn)
            case_c_requeued += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("[RESCUE-C] Failed to requeue '%s': %s", fn, exc)

    if case_c_requeued:
        logger.info("[RESCUE-C] %d documents re-queued for analysis+embedding.", case_c_requeued)

    return {
        "case_a_fixed":    case_a_fixed,
        "case_b_embedded": case_b_embedded,
        "case_b_failed":   case_b_failed,
        "case_c_requeued": case_c_requeued,
    }


def run_full_scan(
    root_folder: str,
    progress_callback: Optional[callable] = None,
) -> dict:
    """
    Execute the complete DocuWise intelligence workflow for a folder.

    Stages:
      1. Scan    — Discover new and changed files, sync to database.
      2. Process — Extract text, analyze with Gemini, generate embeddings.
      3. Detect  — Identify duplicate and similar document pairs.

    This is the single entry point called by the UI layer. All stages run
    sequentially in the calling thread. For background execution, wrap this
    call in a QThread (PyQt6) or threading.Thread in the UI layer.

    Args:
        root_folder:       Absolute path to the folder to scan.
        progress_callback: Optional callable forwarded to
                           process_pending_documents(). Signature:
                               callback(current: int, total: int, filename: str)

    Returns:
        Combined summary dict:
        {
            "scan": {
                "session_id":      int,
                "total_files":     int,
                "new_files":       int,
                "changed_files":   int,
                "unchanged_files": int,
                "failed_files":    int,
            },
            "pipeline": {
                "processed": int,
                "failed":    int,
                "skipped":   int,
            },
            "duplicates": {
                "total_compared":  int,
                "duplicates_found": int,
                "similar_found":   int,
                "errors":          int,
            },
        }

    Raises:
        ValueError: Propagated from scan_folder() if root_folder does not
                    exist or is not a directory.
    """
    started_at = time.monotonic()
    logger.info("=" * 60)
    logger.info("DocuWise full scan starting: '%s'", root_folder)
    logger.info("=" * 60)

    # Ensure DB schema is up to date (idempotent — safe to call every run).
    init_db()

    # ── Stage 0: Mark deleted files as missing ────────────────────────────────
    # Must run before scan so already-indexed files that were physically deleted
    # are flagged 'missing' before the pipeline attempts to process them.
    missing_count = cleanup_missing_files()
    if missing_count:
        logger.info("STAGE 0 — %d file(s) no longer on disk, marked as 'missing'.", missing_count)
    else:
        logger.debug("STAGE 0 — No missing files detected.")

    # ── Stage 1: Scan ────────────────────────────────────────────────────────
    logger.info("STAGE 1/3 — Scanning filesystem...")
    scan_result = scan_folder(root_folder)
    logger.info(
        "Scan complete — total=%d  new=%d  changed=%d  unchanged=%d  failed=%d",
        scan_result["total_files"],
        scan_result["new_files"],
        scan_result["changed_files"],
        scan_result["unchanged_files"],
        scan_result["failed_files"],
    )

    # ── Stage 2: Rescue stalled documents first ───────────────────────────────
    # Fixes docs whose status is inconsistent with their actual data.
    # Must run BEFORE process_pending so that re-queued docs are picked up
    # by the pipeline in the same scan run.
    logger.info("STAGE 2a — Rescuing stalled documents...")
    rescue_result = rescue_stalled_documents()

    # ── Stage 2b: Process pending + rescued documents ─────────────────────────
    logger.info("STAGE 2b — Processing pending documents...")
    pipeline_result = process_pending_documents(progress_callback=progress_callback)

    # ── Stage 3: Detect duplicates ───────────────────────────────────────────
    logger.info("STAGE 3/3 — Detecting duplicates and similar documents...")
    duplicates_result = detect_duplicates()

    elapsed = time.monotonic() - started_at
    logger.info("=" * 60)
    logger.info("DocuWise full scan finished in %.1f seconds.", elapsed)
    logger.info(
        "Summary — scanned=%d  processed=%d  failed=%d  rescued=%d  duplicates=%d  similar=%d",
        scan_result["total_files"],
        pipeline_result["processed"],
        pipeline_result["failed"],
        rescue_result["case_a_fixed"] + rescue_result["case_b_embedded"],
        duplicates_result["duplicates_found"],
        duplicates_result["similar_found"],
    )
    logger.info("=" * 60)

    return {
        "scan":       scan_result,
        "pipeline":   pipeline_result,
        "rescue":     rescue_result,
        "duplicates": duplicates_result,
        "missing":    missing_count,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _report_progress(
    callback: Optional[callable],
    current: int,
    total: int,
    filename: str,
) -> None:
    """
    Invoke the progress callback if one was provided.

    Silently swallows callback exceptions so that a buggy UI callback
    can never abort the processing pipeline.

    Args:
        callback: The callable to invoke, or None.
        current:  1-based index of the document just processed.
        total:    Total number of documents in this batch.
        filename: Bare filename of the document just processed.
    """
    if callback is None:
        return
    try:
        callback(current, total, filename)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Progress callback raised an exception: %s", exc)
