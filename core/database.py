"""
core/database.py — SQLite persistence layer for DocuWise.

Single source of truth for all database operations.
Uses only Python's built-in sqlite3 module.

Rules enforced in this module:
  - Every public function uses `with sqlite3.connect(DB_PATH) as conn`.
  - All rows are returned as plain Python dicts (never bare tuples).
  - No business logic lives here — only data access.
  - WAL journal mode is enabled on every connection for concurrency safety.
"""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from config import DB_PATH, TIMESTAMP_FORMAT


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    """
    Open a SQLite connection with standard settings applied.

    Enables:
      - WAL journal mode for concurrent read/write access.
      - Foreign key enforcement.
      - Row factory so fetchall() returns sqlite3.Row objects.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    """Convert a list of sqlite3.Row objects to a list of plain dicts."""
    return [dict(row) for row in rows]


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    """Convert a single sqlite3.Row to a dict, or return None if row is None."""
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Create the database file and all required tables if they do not exist.

    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS throughout.
    Also creates indexes for the most common query patterns.
    The storage/ directory is created automatically if absent.
    """
    conn = _connect()
    with conn:
        conn.executescript("""
            -- ----------------------------------------------------------------
            -- documents: one row per discovered file
            -- ----------------------------------------------------------------
            CREATE TABLE IF NOT EXISTS documents (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Identity
                file_path           TEXT    NOT NULL UNIQUE,
                filename            TEXT    NOT NULL,
                extension           TEXT    NOT NULL,
                file_size_kb        REAL,

                -- Extraction
                word_count          INTEGER,
                md5_hash            TEXT,
                extracted_text      TEXT,

                -- Embedding (stored as JSON array of floats)
                embedding_json      TEXT,

                -- Gemini analysis
                summary             TEXT,
                category            TEXT,
                subject             TEXT,
                tags_json           TEXT,           -- JSON array of strings
                importance_score    REAL,           -- 0.0 – 1.0

                -- Rule evaluation results
                highlight           INTEGER NOT NULL DEFAULT 0,
                highlight_reason    TEXT,
                deletion_candidate  INTEGER NOT NULL DEFAULT 0,
                deletion_reason     TEXT,

                -- Processing state machine
                -- Values: pending | extracted | embedded | analyzed | completed | failed
                processing_status   TEXT    NOT NULL DEFAULT 'pending',

                -- Filesystem cache (used to detect changes between scans)
                file_created_at     TEXT,
                file_modified_at    TEXT,
                last_scanned_at     TEXT,

                -- Audit timestamps
                created_at          TEXT    NOT NULL,
                updated_at          TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_doc_status
                ON documents(processing_status);

            CREATE INDEX IF NOT EXISTS idx_doc_md5
                ON documents(md5_hash);

            CREATE INDEX IF NOT EXISTS idx_doc_category
                ON documents(category);

            CREATE INDEX IF NOT EXISTS idx_doc_highlight
                ON documents(highlight);

            CREATE INDEX IF NOT EXISTS idx_doc_deletion
                ON documents(deletion_candidate);

            -- ----------------------------------------------------------------
            -- document_relationships: directed edges between document pairs
            -- ----------------------------------------------------------------
            CREATE TABLE IF NOT EXISTS document_relationships (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                source_document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                target_document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,

                -- Values: duplicate | similar | newer_version | related
                relationship_type   TEXT    NOT NULL,
                similarity_score    REAL    NOT NULL,   -- 0.0 – 1.0
                reason              TEXT,

                created_at          TEXT    NOT NULL,

                UNIQUE(source_document_id, target_document_id, relationship_type)
            );

            CREATE INDEX IF NOT EXISTS idx_rel_source
                ON document_relationships(source_document_id);

            CREATE INDEX IF NOT EXISTS idx_rel_target
                ON document_relationships(target_document_id);

            -- ----------------------------------------------------------------
            -- user_rules: natural-language highlight rules
            -- ----------------------------------------------------------------
            CREATE TABLE IF NOT EXISTS user_rules (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                instruction     TEXT    NOT NULL,
                highlight_color TEXT    NOT NULL DEFAULT 'Yellow',
                is_active       INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT    NOT NULL
            );

            -- ----------------------------------------------------------------
            -- scan_sessions: audit log for every scan run
            -- ----------------------------------------------------------------
            CREATE TABLE IF NOT EXISTS scan_sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                root_folder     TEXT    NOT NULL,
                total_files     INTEGER,
                processed_files INTEGER,
                failed_files    INTEGER,
                started_at      TEXT    NOT NULL,
                completed_at    TEXT
            );

            -- ----------------------------------------------------------------
            -- rate_limit_log: persisted API call history for rate limiter
            -- ----------------------------------------------------------------
            CREATE TABLE IF NOT EXISTS rate_limit_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                provider  TEXT    NOT NULL,
                timestamp TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_rate_limit_provider_ts
                ON rate_limit_log (provider, timestamp);

            -- ----------------------------------------------------------------
            -- content_cache: reusable per-content cache keyed by MD5 (Phase 2)
            --
            -- Every expensive operation (OCR, NVIDIA analysis, embedding
            -- generation) is stored here exactly once per unique document
            -- content. Moved / copied / duplicate files reuse these results
            -- without re-running any expensive stage.
            -- ----------------------------------------------------------------
            CREATE TABLE IF NOT EXISTS content_cache (
                md5_hash                TEXT PRIMARY KEY,

                -- Extracted text layers
                native_text             TEXT,   -- text from PyMuPDF / python-docx / plain read
                ocr_text                TEXT,   -- text recovered via OCR (may be NULL)
                final_text              TEXT,   -- merged text actually used downstream
                extraction_method       TEXT,   -- native | hybrid | ocr_only | image_only

                -- Embedding (JSON array of floats)
                embedding_json          TEXT,

                -- LLM analysis results
                summary                 TEXT,
                category                TEXT,
                subject                 TEXT,
                tags_json               TEXT,
                importance_score        REAL,
                analysis_source         TEXT,   -- nvidia | gemini | fallback | cached

                -- OCR provenance / metrics
                ocr_engine              TEXT,
                ocr_version             TEXT,
                ocr_confidence          REAL,
                ocr_processing_time_ms  INTEGER,
                ocr_pages_processed     INTEGER,

                -- Audit timestamps
                created_at              TEXT NOT NULL,
                updated_at              TEXT NOT NULL
            );

            -- ----------------------------------------------------------------
            -- knowledge_profiles: deep knowledge extracted per document
            --   (Phase 2 — Knowledge-Aware Semantic Search)
            --
            -- One row per fully-analyzed document. Stores concepts, entities,
            -- domains, and other semantic metadata as JSON. Kept separate from
            -- the documents table to avoid bloating the 25+ column main table
            -- and to allow independent rebuilds.
            -- ----------------------------------------------------------------
            CREATE TABLE IF NOT EXISTS knowledge_profiles (
                document_id         INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,

                -- Semantic knowledge (all JSON)
                concepts_json       TEXT,           -- ["operating systems", "concurrency"]
                entities_json       TEXT,           -- [{"name":"Mutex","type":"concept"}]
                domains_json        TEXT,           -- ["computer science"]
                doc_type            TEXT,           -- "lecture notes" | "research paper" | ...
                difficulty          TEXT,           -- "beginner" | "intermediate" | "advanced"
                prerequisites_json  TEXT,           -- ["data structures"]
                related_topics_json TEXT,           -- ["distributed systems"]
                language            TEXT,           -- "en" | "hi" | "mixed"
                confidence          REAL,           -- extraction confidence 0.0-1.0

                -- Audit timestamps
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_kp_doc
                ON knowledge_profiles(document_id);

            -- ----------------------------------------------------------------
            -- search_history: recent queries for autocomplete & analytics
            --   (Phase 2 — Knowledge-Aware Semantic Search)
            -- ----------------------------------------------------------------
            CREATE TABLE IF NOT EXISTS search_history (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                query               TEXT NOT NULL,
                result_count        INTEGER,
                searched_at         TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sh_query
                ON search_history(query);

            -- ----------------------------------------------------------------
            -- search_clicks: instrumentation for Phase 4
            -- ----------------------------------------------------------------
            CREATE TABLE IF NOT EXISTS search_clicks (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                query               TEXT    NOT NULL,
                document_id         INTEGER NOT NULL,
                position            INTEGER,
                clicked_at          TEXT    NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
            );
            
            CREATE INDEX IF NOT EXISTS idx_search_clicks_doc ON search_clicks(document_id);
        """)

    # ── Column migrations (idempotent ALTER TABLE) ──────────────────────────
    # analysis_source tracks whether analysis came from 'nvidia', 'gemini',
    # 'fallback', or 'cached'. Added post-initial schema.
    _add_column_if_missing(
        table="documents",
        column="analysis_source",
        definition="TEXT DEFAULT NULL",
    )

    # ── Extraction metadata (Phase 6) ───────────────────────────────────────
    # These columns describe HOW a document's text was obtained and, when OCR
    # was involved, its provenance and cost. All nullable so pre-existing rows
    # migrate cleanly (a NULL extraction_method is treated as 'native' by the
    # dashboard aggregates below).
    _extraction_columns: dict[str, str] = {
        "extraction_method":      "TEXT DEFAULT NULL",   # native|hybrid|ocr_only|image_only
        "ocr_engine":             "TEXT DEFAULT NULL",
        "ocr_version":            "TEXT DEFAULT NULL",
        "ocr_confidence":         "REAL DEFAULT NULL",
        "ocr_pages_processed":    "INTEGER DEFAULT 0",
        "ocr_pages_skipped":      "INTEGER DEFAULT 0",
        "ocr_processing_time_ms": "INTEGER DEFAULT 0",
        "ocr_cached":             "INTEGER DEFAULT 0",    # 1 when OCR text came from cache
    }
    for _col, _defn in _extraction_columns.items():
        _add_column_if_missing(table="documents", column=_col, definition=_defn)

    # ── Knowledge Cache columns on content_cache (Phase 2 — Semantic Search) ──
    # These extend the content_cache so that knowledge profiles are restored
    # alongside analysis/embedding/OCR data for byte-identical files.
    _knowledge_cache_columns: dict[str, str] = {
        "concepts_json":       "TEXT DEFAULT NULL",
        "entities_json":       "TEXT DEFAULT NULL",
        "domains_json":        "TEXT DEFAULT NULL",
        "doc_type":            "TEXT DEFAULT NULL",
        "difficulty":          "TEXT DEFAULT NULL",
        "prerequisites_json":  "TEXT DEFAULT NULL",
        "related_topics_json": "TEXT DEFAULT NULL",
        "language":            "TEXT DEFAULT NULL",
    }
    for _col, _defn in _knowledge_cache_columns.items():
        _add_column_if_missing(table="content_cache", column=_col, definition=_defn)


def _add_column_if_missing(table: str, column: str, definition: str) -> None:
    """
    Add a column to an existing table if it does not already exist.
    Safe to call on every startup — silently skips if already present.
    """
    conn = _connect()
    with conn:
        existing = [
            row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        ]
    if column not in existing:
        conn = _connect()
        with conn:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        import logging as _log
        _log.getLogger(__name__).info(
            "DB migration: added column '%s.%s'.", table, column
        )


# ---------------------------------------------------------------------------
# documents — write operations
# ---------------------------------------------------------------------------

def insert_document(
    file_path: str,
    filename: str,
    extension: str,
    file_size_kb: float,
    file_created_at: Optional[str] = None,
    file_modified_at: Optional[str] = None,
) -> None:
    """
    Insert a newly discovered document record.

    Uses INSERT OR IGNORE so that re-scanning a folder containing already-indexed
    files is safe and idempotent — existing rows are never overwritten here.
    Use update_document_* functions to modify existing records.

    Args:
        file_path:        Absolute path to the file. Used as the unique key.
        filename:         Bare filename including extension (e.g. 'report.pdf').
        extension:        Lowercased file extension (e.g. '.pdf').
        file_size_kb:     File size in kilobytes derived from os.stat().
        file_created_at:  UTC ISO-8601 string from os.stat().st_ctime. Optional.
        file_modified_at: UTC ISO-8601 string from os.stat().st_mtime. Optional.
    """
    now = _now()
    conn = _connect()
    with conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO documents (
                file_path, filename, extension, file_size_kb,
                file_created_at, file_modified_at, last_scanned_at,
                processing_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                file_path, filename, extension, file_size_kb,
                file_created_at, file_modified_at, now,
                now, now,
            ),
        )


def update_document_extraction(
    file_path: str,
    word_count: int,
    md5_hash: str,
    extracted_text: str,
    extraction_method: Optional[str] = None,
    ocr_engine: Optional[str] = None,
    ocr_version: Optional[str] = None,
    ocr_confidence: Optional[float] = None,
    ocr_pages_processed: int = 0,
    ocr_pages_skipped: int = 0,
    ocr_processing_time_ms: int = 0,
    ocr_cached: int = 0,
) -> None:
    """
    Persist text extraction results (and optional OCR metadata) and advance
    status to 'extracted'.

    Called by extractor.py after successfully reading a document's content.
    The OCR-related parameters are optional so callers that do not use OCR
    (DOCX / TXT / native PDF) can invoke this exactly as before.

    Args:
        file_path:              Absolute path identifying the target document row.
        word_count:             Whitespace-delimited word count of the final text.
        md5_hash:               MD5 hex-digest of the raw file bytes.
        extracted_text:         Final plain-text content used downstream.
        extraction_method:      native | hybrid | ocr_only | image_only (Phase 6).
        ocr_engine:             OCR engine name, or None if OCR was not used.
        ocr_version:            OCR engine version tag, or None.
        ocr_confidence:         Mean OCR confidence 0.0–1.0, or None.
        ocr_pages_processed:    Number of pages actually OCR'd.
        ocr_pages_skipped:      Number of pages that already had native text.
        ocr_processing_time_ms: Total OCR wall-clock time in milliseconds.
        ocr_cached:             1 if the OCR text was reused from the cache.
    """
    now = _now()
    conn = _connect()
    with conn:
        conn.execute(
            """
            UPDATE documents
               SET word_count             = ?,
                   md5_hash               = ?,
                   extracted_text         = ?,
                   extraction_method      = ?,
                   ocr_engine             = ?,
                   ocr_version            = ?,
                   ocr_confidence         = ?,
                   ocr_pages_processed    = ?,
                   ocr_pages_skipped      = ?,
                   ocr_processing_time_ms = ?,
                   ocr_cached             = ?,
                   processing_status      = 'extracted',
                   last_scanned_at        = ?,
                   updated_at             = ?
             WHERE file_path = ?
            """,
            (
                word_count, md5_hash, extracted_text,
                extraction_method, ocr_engine, ocr_version, ocr_confidence,
                ocr_pages_processed, ocr_pages_skipped, ocr_processing_time_ms,
                ocr_cached,
                now, now, file_path,
            ),
        )


def update_document_embedding(
    file_path: str,
    embedding_json: str,
) -> None:
    """
    Store the serialised embedding vector and advance status to 'embedded'.

    Called by embedder.py after generating and (optionally) saving the vector.
    The embedding is stored as a JSON array of floats for portability.

    Args:
        file_path:      Absolute path identifying the target document row.
        embedding_json: JSON-encoded list of floats, e.g. '[0.12, -0.34, ...]'.
    """
    now = _now()
    conn = _connect()
    with conn:
        conn.execute(
            """
            UPDATE documents
               SET embedding_json     = ?,
                   processing_status  = 'embedded',
                   updated_at         = ?
             WHERE file_path = ?
            """,
            (embedding_json, now, file_path),
        )


def update_document_analysis(
    file_path: str,
    summary: str,
    category: str,
    subject: str,
    tags_json: str,
    importance_score: float,
    highlight: int,
    highlight_reason: Optional[str],
    deletion_candidate: int,
    deletion_reason: Optional[str],
    analysis_source: Optional[str] = None,
) -> None:
    """
    Persist LLM analysis results and advance processing_status to 'analyzed'.

    Args:
        file_path:          Absolute path identifying the target document row.
        summary:            Short LLM-generated summary of the document content.
        category:           Category label (must be one of DEFAULT_CATEGORIES).
        subject:            Fine-grained subject or topic string.
        tags_json:          JSON array of keyword tags, e.g. '["tax", "2023"]'.
        importance_score:   Integer 1-10 representing the document's keep-value.
        highlight:          1 if the document matches an active rule, else 0.
        highlight_reason:   Human-readable explanation for the highlight flag.
        deletion_candidate: 1 if the document is suggested for deletion, else 0.
        deletion_reason:    Human-readable explanation for the deletion suggestion.
        analysis_source:    'nvidia' | 'gemini' | 'fallback' | 'cached' | None.
    """
    now = _now()
    conn = _connect()
    with conn:
        conn.execute(
            """
            UPDATE documents
               SET summary            = ?,
                   category           = ?,
                   subject            = ?,
                   tags_json          = ?,
                   importance_score   = ?,
                   highlight          = ?,
                   highlight_reason   = ?,
                   deletion_candidate = ?,
                   deletion_reason    = ?,
                   analysis_source    = ?,
                   processing_status  = 'analyzed',
                   updated_at         = ?
             WHERE file_path = ?
            """,
            (
                summary, category, subject, tags_json, importance_score,
                highlight, highlight_reason,
                deletion_candidate, deletion_reason,
                analysis_source,
                now, file_path,
            ),
        )


def update_document_status(
    file_path: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """
    Set the processing_status of a document to any valid state.

    Used to mark documents as 'completed' or 'failed', and to reset them
    back to 'pending' when the scanner detects a changed file on disk.

    Valid status values:
        pending | extracted | embedded | analyzed | completed | failed

    Args:
        file_path:     Absolute path identifying the target document row.
        status:        One of the valid processing_status values.
        error_message: Optional error detail written to the summary field
                       when status='failed', to surface the reason in the UI.
    """
    now = _now()
    conn = _connect()
    with conn:
        if status == "failed" and error_message:
            conn.execute(
                """
                UPDATE documents
                   SET processing_status = ?,
                       summary           = ?,
                       updated_at        = ?
                 WHERE file_path = ?
                """,
                (status, f"[ERROR] {error_message}", now, file_path),
            )
        elif status == "pending":
            # Full reset — clear all derived data so the pipeline reruns cleanly.
            conn.execute(
                """
                UPDATE documents
                   SET processing_status  = 'pending',
                       word_count         = NULL,
                       md5_hash           = NULL,
                       extracted_text     = NULL,
                       embedding_json     = NULL,
                       summary            = NULL,
                       category           = NULL,
                       subject            = NULL,
                       tags_json          = NULL,
                       importance_score   = NULL,
                       highlight          = 0,
                       highlight_reason   = NULL,
                       deletion_candidate = 0,
                       deletion_reason    = NULL,
                       updated_at         = ?
                 WHERE file_path = ?
                """,
                (now, file_path),
            )
        else:
            conn.execute(
                """
                UPDATE documents
                   SET processing_status = ?,
                       updated_at        = ?
                 WHERE file_path = ?
                """,
                (status, now, file_path),
            )


# ---------------------------------------------------------------------------
# documents — read operations
# ---------------------------------------------------------------------------

def find_by_md5(md5_hash: str, exclude_file_path: str = "") -> Optional[dict]:
    """
    Return the first fully-processed document with the given MD5 hash.

    Used by the pipeline to detect when a copied / moved / renamed file has
    already been analyzed, so we can skip the LLM call and embedding step.

    Args:
        md5_hash:          Hex-digest to search for.
        exclude_file_path: Path of the *current* document being processed —
                           excluded from results so a document never matches itself.

    Returns:
        A document dict (all columns) if a cache source is found, else None.
    """
    conn = _connect()
    with conn:
        row = conn.execute(
            """
            SELECT * FROM documents
             WHERE md5_hash = ?
               AND processing_status IN ('embedded', 'analyzed', 'completed')
               AND file_path != ?
             ORDER BY updated_at DESC
             LIMIT 1
            """,
            (md5_hash, exclude_file_path),
        ).fetchone()
    return dict(row) if row else None


def copy_analysis_from_cache(
    file_path: str,
    source: dict,
) -> None:
    """
    Copy all analysis + embedding data from *source* into *file_path*'s row
    and set processing_status to 'embedded'.

    This is the write-side of the MD5 cache: called when the pipeline finds
    that a file's content was already fully processed under a different path.

    Args:
        file_path: Absolute path of the document being fast-tracked.
        source:    Full document dict of the cache-source document.
    """
    now = _now()
    conn = _connect()
    with conn:
        conn.execute(
            """
            UPDATE documents
               SET summary            = ?,
                   category           = ?,
                   subject            = ?,
                   tags_json          = ?,
                   importance_score   = ?,
                   deletion_candidate = ?,
                   deletion_reason    = ?,
                   highlight          = ?,
                   highlight_reason   = ?,
                   analysis_source    = 'cached',
                   embedding_json     = ?,
                   processing_status  = 'embedded',
                   updated_at         = ?
             WHERE file_path = ?
            """,
            (
                source.get("summary"),
                source.get("category"),
                source.get("subject"),
                source.get("tags_json"),
                source.get("importance_score"),
                source.get("deletion_candidate", 0),
                source.get("deletion_reason"),
                source.get("highlight", 0),
                source.get("highlight_reason"),
                source.get("embedding_json"),
                now,
                file_path,
            ),
        )


def get_document(file_path: str) -> Optional[dict]:
    """
    Return a single document row as a dict, or None if not found.

    Public accessor used by the content-cache service and any caller that needs
    the full row without embedding a raw SELECT.

    Args:
        file_path: Absolute path used as the unique document key.

    Returns:
        Document dict (all columns) or None.
    """
    conn = _connect()
    with conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE file_path = ? LIMIT 1",
            (file_path,),
        ).fetchone()
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# knowledge_profiles — semantic knowledge per document (Phase 2)
# ---------------------------------------------------------------------------

def upsert_knowledge_profile(
    document_id: int,
    *,
    concepts_json: Optional[str] = None,
    entities_json: Optional[str] = None,
    domains_json: Optional[str] = None,
    doc_type: Optional[str] = None,
    difficulty: Optional[str] = None,
    prerequisites_json: Optional[str] = None,
    related_topics_json: Optional[str] = None,
    language: Optional[str] = None,
    confidence: Optional[float] = None,
) -> None:
    """
    Insert or replace the knowledge profile for a document.

    Uses INSERT OR REPLACE — if a profile already exists for *document_id*,
    the entire row is replaced. This is safe because knowledge profiles are
    always written as a complete unit from a single LLM response.

    Args:
        document_id:         Primary key of the document (documents.id).
        concepts_json:       JSON array of concept strings.
        entities_json:       JSON array of entity objects.
        domains_json:        JSON array of domain strings.
        doc_type:            Document type classification.
        difficulty:          Difficulty level string.
        prerequisites_json:  JSON array of prerequisite topic strings.
        related_topics_json: JSON array of related topic strings.
        language:            Detected language code.
        confidence:          Extraction confidence score 0.0–1.0.
    """
    now = _now()
    conn = _connect()
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO knowledge_profiles (
                document_id,
                concepts_json, entities_json, domains_json,
                doc_type, difficulty,
                prerequisites_json, related_topics_json,
                language, confidence,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                concepts_json, entities_json, domains_json,
                doc_type, difficulty,
                prerequisites_json, related_topics_json,
                language, confidence,
                now, now,
            ),
        )


def get_knowledge_profile(document_id: int) -> Optional[dict]:
    """
    Return the knowledge profile for a document, or None if not yet extracted.

    Args:
        document_id: Primary key of the document (documents.id).

    Returns:
        Knowledge profile dict (all columns) or None.
    """
    conn = _connect()
    with conn:
        row = conn.execute(
            "SELECT * FROM knowledge_profiles WHERE document_id = ? LIMIT 1",
            (document_id,),
        ).fetchone()
    return _row_to_dict(row)


def delete_knowledge_profile(document_id: int) -> None:
    """
    Delete the knowledge profile for a document (e.g. on re-analysis).

    Args:
        document_id: Primary key of the document (documents.id).
    """
    conn = _connect()
    with conn:
        conn.execute(
            "DELETE FROM knowledge_profiles WHERE document_id = ?",
            (document_id,),
        )


# ---------------------------------------------------------------------------
# content_cache — reusable per-content cache (Phase 2)
# ---------------------------------------------------------------------------

# Whitelist of writable content_cache columns. Guards content_cache_upsert()
# against SQL injection via dynamic column names and documents the schema.
_CONTENT_CACHE_COLUMNS: frozenset[str] = frozenset({
    "native_text", "ocr_text", "final_text", "extraction_method",
    "embedding_json", "summary", "category", "subject", "tags_json",
    "importance_score", "analysis_source",
    "ocr_engine", "ocr_version", "ocr_confidence",
    "ocr_processing_time_ms", "ocr_pages_processed",
    # Knowledge Cache columns (Phase 2 — Semantic Search)
    "concepts_json", "entities_json", "domains_json",
    "doc_type", "difficulty", "prerequisites_json",
    "related_topics_json", "language",
})


def content_cache_get(md5_hash: str) -> Optional[dict]:
    """
    Return the content_cache row for *md5_hash*, or None on a cache miss.

    Args:
        md5_hash: MD5 hex-digest identifying the unique document content.

    Returns:
        Cache row dict (all columns) or None.
    """
    if not md5_hash:
        return None
    conn = _connect()
    with conn:
        row = conn.execute(
            "SELECT * FROM content_cache WHERE md5_hash = ? LIMIT 1",
            (md5_hash,),
        ).fetchone()
    return _row_to_dict(row)


def content_cache_upsert(md5_hash: str, **fields) -> None:
    """
    Insert or update a content_cache row, writing only the provided columns.

    Existing columns not present in *fields* are preserved on update — this lets
    the extractor seed the text layers first and the pipeline fill in the
    embedding + analysis later without clobbering earlier data.

    Args:
        md5_hash: Primary key (MD5 hex-digest). Required and non-empty.
        **fields: Any subset of _CONTENT_CACHE_COLUMNS to write.

    Raises:
        ValueError: If md5_hash is empty or an unknown column is supplied.
    """
    if not md5_hash:
        raise ValueError("content_cache_upsert requires a non-empty md5_hash.")

    unknown = set(fields) - _CONTENT_CACHE_COLUMNS
    if unknown:
        raise ValueError(f"Unknown content_cache column(s): {sorted(unknown)}")

    now = _now()
    # Write every provided column. On UPDATE, COALESCE(new, existing) below means
    # a None value never erases previously stored data — so partial upserts
    # (text first, embedding + analysis later) compose safely.
    columns = list(fields.keys())

    conn = _connect()
    with conn:
        insert_cols = ["md5_hash"] + columns + ["created_at", "updated_at"]
        placeholders = ", ".join("?" for _ in insert_cols)
        values = [md5_hash] + [fields[c] for c in columns] + [now, now]

        # On conflict, update each provided column. Use COALESCE(new, existing)
        # so a None in *fields* never erases a previously stored value.
        update_clause = ", ".join(
            f"{c} = COALESCE(excluded.{c}, content_cache.{c})" for c in columns
        )
        update_clause = (update_clause + ", " if update_clause else "") + "updated_at = excluded.updated_at"

        conn.execute(
            f"""
            INSERT INTO content_cache ({", ".join(insert_cols)})
            VALUES ({placeholders})
            ON CONFLICT(md5_hash) DO UPDATE SET {update_clause}
            """,
            values,
        )


def restore_document_from_cache(file_path: str, entry: dict) -> None:
    """
    Write a full content_cache entry into a document row and mark it 'embedded'.

    This is the read-side of the Content Cache: called when a file's MD5 already
    has a complete cache entry (moved / copied / duplicate content). It restores
    the final text, embedding, analysis, and extraction/OCR metadata in a single
    UPDATE so no expensive stage re-runs.

    Args:
        file_path: Absolute path of the document being fast-tracked.
        entry:     A content_cache row dict (from content_cache_get) — or any
                   dict exposing the same keys (used by the documents-MD5
                   backward-compatibility fallback).
    """
    now = _now()
    final_text = entry.get("final_text") or entry.get("extracted_text") or ""
    word_count = len(final_text.split()) if final_text else 0
    # Only count this as an OCR-cache reuse if the cached content actually
    # involved OCR — a restored native/DOCX/TXT document did not.
    ocr_cached = 1 if (entry.get("ocr_pages_processed") or entry.get("ocr_text")) else 0

    conn = _connect()
    with conn:
        conn.execute(
            """
            UPDATE documents
               SET word_count             = ?,
                   extracted_text         = ?,
                   embedding_json         = ?,
                   summary                = ?,
                   category               = ?,
                   subject                = ?,
                   tags_json              = ?,
                   importance_score       = ?,
                   deletion_candidate     = ?,
                   deletion_reason        = ?,
                   highlight              = ?,
                   highlight_reason       = ?,
                   analysis_source        = 'cached',
                   extraction_method      = ?,
                   ocr_engine             = ?,
                   ocr_version            = ?,
                   ocr_confidence         = ?,
                   ocr_pages_processed    = ?,
                   ocr_processing_time_ms = ?,
                   ocr_cached             = ?,
                   processing_status      = 'embedded',
                   last_scanned_at        = ?,
                   updated_at             = ?
             WHERE file_path = ?
            """,
            (
                word_count,
                final_text,
                entry.get("embedding_json"),
                entry.get("summary"),
                entry.get("category"),
                entry.get("subject"),
                entry.get("tags_json"),
                entry.get("importance_score"),
                entry.get("deletion_candidate", 0) or 0,
                entry.get("deletion_reason"),
                entry.get("highlight", 0) or 0,
                entry.get("highlight_reason"),
                entry.get("extraction_method"),
                entry.get("ocr_engine"),
                entry.get("ocr_version"),
                entry.get("ocr_confidence"),
                entry.get("ocr_pages_processed", 0) or 0,
                entry.get("ocr_processing_time_ms", 0) or 0,
                ocr_cached,
                now, now, file_path,
            ),
        )


def get_all_documents() -> list[dict]:
    """
    Return every document row ordered alphabetically by filename.

    Returns:
        List of dicts with all column names as keys. Empty list if no rows exist.
    """
    conn = _connect()
    with conn:
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY filename COLLATE NOCASE"
        ).fetchall()
    return _rows_to_dicts(rows)


def get_documents_by_status(status: str) -> list[dict]:
    """
    Return all documents with the given processing_status.

    Used by each pipeline stage to load its work queue, e.g.:
        get_documents_by_status('pending')   → extractor queue
        get_documents_by_status('extracted') → embedder queue
        get_documents_by_status('embedded')  → analyzer queue
        get_documents_by_status('failed')    → error review list
        get_documents_by_status('missing')   → files deleted from disk

    Args:
        status: One of: pending | extracted | embedded | analyzed | completed | failed | missing

    Returns:
        List of document dicts matching the given status.
    """
    conn = _connect()
    with conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE processing_status = ? ORDER BY filename COLLATE NOCASE",
            (status,),
        ).fetchall()
    return _rows_to_dicts(rows)


def get_documents_for_ocr_retry() -> list[dict]:
    """
    Return image-only documents that predate OCR and are worth re-attempting.

    These are rows with processing_status = 'image_only' whose extraction_method
    is still NULL — i.e. they were marked image-only before OCR existed and have
    never been through an OCR attempt. Once OCR runs (success or a definitive
    'image_only' verdict), extraction_method is set, so a document is retried at
    most once and never loops across scans.

    Returns:
        List of document dicts eligible for a one-time OCR retry.
    """
    conn = _connect()
    with conn:
        rows = conn.execute(
            """
            SELECT * FROM documents
             WHERE processing_status = 'image_only'
               AND extraction_method IS NULL
             ORDER BY filename COLLATE NOCASE
            """
        ).fetchall()
    return _rows_to_dicts(rows)


def get_deletion_candidates() -> list[dict]:
    """
    Return all documents flagged as candidates for deletion.

    Returns:
        List of document dicts where deletion_candidate = 1.
    """
    conn = _connect()
    with conn:
        rows = conn.execute(
            """
            SELECT * FROM documents
             WHERE deletion_candidate = 1
             ORDER BY importance_score ASC, filename COLLATE NOCASE
            """
        ).fetchall()
    return _rows_to_dicts(rows)


def get_highlighted_documents() -> list[dict]:
    """
    Return all documents matched by a user-defined highlight rule.

    Returns:
        List of document dicts where highlight = 1.
    """
    conn = _connect()
    with conn:
        rows = conn.execute(
            """
            SELECT * FROM documents
             WHERE highlight = 1
             ORDER BY filename COLLATE NOCASE
            """
        ).fetchall()
    return _rows_to_dicts(rows)


def document_exists(file_path: str) -> bool:
    """
    Check whether a document with the given absolute path is in the database.

    Used by scanner.py to distinguish new files from previously indexed ones.

    Args:
        file_path: Absolute path to check.

    Returns:
        True if a matching row exists, False otherwise.
    """
    conn = _connect()
    with conn:
        row = conn.execute(
            "SELECT 1 FROM documents WHERE file_path = ? LIMIT 1",
            (file_path,),
        ).fetchone()
    return row is not None


def get_missing_documents() -> list[dict]:
    """
    Return all documents whose file no longer exists on disk.

    These are rows with processing_status = 'missing', set by
    cleanup_missing_files() during the scan pre-pass.

    Returns:
        List of document dicts ordered alphabetically by filename.
    """
    conn = _connect()
    with conn:
        rows = conn.execute(
            """
            SELECT * FROM documents
             WHERE processing_status = 'missing'
             ORDER BY filename COLLATE NOCASE
            """
        ).fetchall()
    return _rows_to_dicts(rows)


def cleanup_missing_files() -> int:
    """
    Iterate all document records and mark any whose file_path no longer
    exists on disk with processing_status = 'missing'.

    This is a non-destructive operation — the record is kept in the database
    for audit purposes and UI display, but is excluded from all pipeline
    stages (extraction, analysis, embedding).

    Returns:
        Number of documents newly marked as 'missing'.
    """
    import os as _os
    import logging as _log
    _logger = _log.getLogger(__name__)

    conn = _connect()
    with conn:
        rows = conn.execute(
            """
            SELECT file_path, filename FROM documents
             WHERE processing_status != 'missing'
            """
        ).fetchall()

    marked = 0
    now = _now()
    for row in rows:
        fp, fn = row["file_path"], row["filename"]
        if not _os.path.exists(fp):
            try:
                conn2 = _connect()
                with conn2:
                    conn2.execute(
                        """
                        UPDATE documents
                           SET processing_status = 'missing',
                               updated_at        = ?
                         WHERE file_path = ?
                        """,
                        (now, fp),
                    )
                _logger.info("[MISSING] '%s' no longer on disk — marked as missing.", fn)
                marked += 1
            except Exception as exc:  # noqa: BLE001
                _logger.error("Failed to mark '%s' as missing: %s", fn, exc)

    return marked


# ---------------------------------------------------------------------------
# document_relationships
# ---------------------------------------------------------------------------

def insert_relationship(
    source_document_id: int,
    target_document_id: int,
    relationship_type: str,
    similarity_score: float,
    reason: Optional[str] = None,
) -> None:
    """
    Insert a directed relationship between two documents.

    Uses INSERT OR IGNORE — if the same (source, target, type) triple already
    exists, the row is silently skipped. This makes bulk insertion safe to retry.

    Relationship type values:
        duplicate    — near-identical content (similarity ≥ SIMILARITY_THRESHOLD)
        similar      — related content (similarity ≥ NEAR_DUPLICATE_THRESHOLD)
        newer_version — likely a revised copy based on content + filename heuristic
        related      — thematically linked documents

    Args:
        source_document_id: Primary key of the source document.
        target_document_id: Primary key of the target document.
        relationship_type:  One of the relationship type values above.
        similarity_score:   Cosine similarity score in range 0.0–1.0.
        reason:             Optional human-readable explanation for the relationship.
    """
    now = _now()
    conn = _connect()
    with conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO document_relationships (
                source_document_id, target_document_id,
                relationship_type, similarity_score, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                source_document_id, target_document_id,
                relationship_type, similarity_score, reason, now,
            ),
        )


def get_relationships(document_id: int) -> list[dict]:
    """
    Return all relationships where the given document is the source.

    Joins against the documents table to include filename and file_path
    of the related target document, making results immediately useful
    for display without a second query.

    Args:
        document_id: Primary key of the source document.

    Returns:
        List of relationship dicts including target document identity fields.
    """
    conn = _connect()
    with conn:
        rows = conn.execute(
            """
            SELECT
                dr.id,
                dr.source_document_id,
                dr.target_document_id,
                dr.relationship_type,
                dr.similarity_score,
                dr.reason,
                dr.created_at,
                d.filename      AS target_filename,
                d.file_path     AS target_file_path,
                d.category      AS target_category
            FROM document_relationships dr
            JOIN documents d ON d.id = dr.target_document_id
            WHERE dr.source_document_id = ?
            ORDER BY dr.similarity_score DESC
            """,
            (document_id,),
        ).fetchall()
    return _rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# user_rules
# ---------------------------------------------------------------------------

def save_rule(instruction: str, highlight_color: str = "Yellow") -> int:
    """
    Deactivate all existing rules and insert a new active rule.

    Only one rule is active at a time. Calling this function replaces whatever
    rule was previously active. The rule engine always reads the active rule
    via get_active_rule() before evaluating documents.

    Args:
        instruction:     Natural-language instruction, e.g.
                         "Highlight all documents related to electrical engineering."
        highlight_color: Display name of the highlight color (must be a key in
                         config.HIGHLIGHT_COLORS). Defaults to 'Yellow'.

    Returns:
        The integer primary key of the newly inserted rule row.
    """
    now = _now()
    conn = _connect()
    with conn:
        conn.execute("UPDATE user_rules SET is_active = 0")
        cursor = conn.execute(
            """
            INSERT INTO user_rules (instruction, highlight_color, is_active, created_at)
            VALUES (?, ?, 1, ?)
            """,
            (instruction, highlight_color, now),
        )
        return cursor.lastrowid


def get_active_rule() -> Optional[dict]:
    """
    Return the currently active user rule, or None if no rule has been set.

    The rule engine calls this before each analysis pass to determine what
    instruction to inject into the Gemini prompt.

    Returns:
        Dict with rule columns as keys, or None.
    """
    conn = _connect()
    with conn:
        row = conn.execute(
            "SELECT * FROM user_rules WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# scan_sessions
# ---------------------------------------------------------------------------

def start_scan_session(root_folder: str) -> int:
    """
    Record the start of a new scan session and return its ID.

    Called by scanner.py at the very beginning of a scan before any files
    are processed. The session ID is passed to complete_scan_session() later.

    Args:
        root_folder: Absolute path of the folder being scanned.

    Returns:
        Integer primary key of the newly created scan_sessions row.
    """
    now = _now()
    conn = _connect()
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO scan_sessions (root_folder, started_at)
            VALUES (?, ?)
            """,
            (root_folder, now),
        )
        return cursor.lastrowid


def complete_scan_session(
    session_id: int,
    total_files: int,
    processed_files: int,
    failed_files: int,
) -> None:
    """
    Update a scan session with final file counts and a completion timestamp.

    Called by scanner.py after all files have been discovered and queued.
    Processing may still be ongoing in background threads at this point —
    this records the scan phase completion, not full pipeline completion.

    Args:
        session_id:      ID returned by start_scan_session().
        total_files:     Total number of supported files discovered.
        processed_files: Files successfully inserted or updated in the DB.
        failed_files:    Files that could not be read or processed.
    """
    now = _now()
    conn = _connect()
    with conn:
        conn.execute(
            """
            UPDATE scan_sessions
               SET total_files     = ?,
                   processed_files = ?,
                   failed_files    = ?,
                   completed_at    = ?
             WHERE id = ?
            """,
            (total_files, processed_files, failed_files, now, session_id),
        )


# ---------------------------------------------------------------------------
# Dashboard metrics (Issue 7)
# ---------------------------------------------------------------------------

def get_total_documents() -> int:
    """Return the total number of documents indexed in the database."""
    conn = _connect()
    with conn:
        row = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
    return row[0] if row else 0


def get_total_embedded() -> int:
    """Return the number of documents with processing_status = 'embedded'."""
    conn = _connect()
    with conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE processing_status = 'embedded'"
        ).fetchone()
    return row[0] if row else 0


def get_total_failed() -> int:
    """Return the number of documents with processing_status = 'failed'."""
    conn = _connect()
    with conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE processing_status = 'failed'"
        ).fetchone()
    return row[0] if row else 0


def get_total_image_only() -> int:
    """Return the number of image-based PDFs that could not be text-extracted."""
    conn = _connect()
    with conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE processing_status = 'image_only'"
        ).fetchone()
    return row[0] if row else 0


def get_total_duplicates() -> int:
    """Return the total number of duplicate/similar relationships detected."""
    conn = _connect()
    with conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM document_relationships"
        ).fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Extraction / OCR / cache dashboard metrics (Phase 10)
# ---------------------------------------------------------------------------

def get_extraction_metrics(path_prefix: Optional[str] = None) -> dict:
    """
    Aggregate extraction-method and OCR/cache metrics for the dashboard.

    Rows predating the OCR feature have a NULL extraction_method; they are
    bucketed by processing_status so the numbers stay meaningful after upgrade:
    a NULL method with status 'image_only' counts as an image-only document,
    everything else with usable text counts as 'native'.

    Args:
        path_prefix: Optional folder filter. When given, only documents whose
                     file_path starts with this prefix are counted.

    Returns:
        {
            "native_documents":   int,
            "hybrid_documents":   int,
            "ocr_only_documents": int,
            "image_only_documents": int,
            "ocr_cache_hits":     int,   # docs whose OCR text came from cache
            "content_cache_hits": int,   # docs restored wholesale from cache
            "api_calls_saved":    int,   # NVIDIA calls avoided via cache
            "embeddings_reused":  int,   # embeddings reused via cache
            "avg_ocr_time_ms":    float, # mean OCR time over OCR'd documents
        }
    """
    where = ""
    params: list = []
    if path_prefix:
        where = " WHERE file_path LIKE ?"
        params.append(path_prefix.rstrip("\\/") + "\\" + "%")

    conn = _connect()
    with conn:
        rows = conn.execute(
            f"""
            SELECT extraction_method, processing_status,
                   ocr_cached, analysis_source,
                   ocr_processing_time_ms, ocr_pages_processed
            FROM documents{where}
            """,
            params,
        ).fetchall()

    metrics = {
        "native_documents": 0,
        "hybrid_documents": 0,
        "ocr_only_documents": 0,
        "image_only_documents": 0,
        "ocr_cache_hits": 0,
        "content_cache_hits": 0,
        "api_calls_saved": 0,
        "embeddings_reused": 0,
        "avg_ocr_time_ms": 0.0,
    }

    ocr_times: list[int] = []
    for row in rows:
        method = row["extraction_method"]
        status = row["processing_status"]

        # Backward-compatible bucketing for pre-OCR rows.
        if method is None:
            method = "image_only" if status == "image_only" else "native"

        if method == "native":
            metrics["native_documents"] += 1
        elif method == "hybrid":
            metrics["hybrid_documents"] += 1
        elif method == "ocr_only":
            metrics["ocr_only_documents"] += 1
        elif method == "image_only":
            metrics["image_only_documents"] += 1

        if row["ocr_cached"]:
            metrics["ocr_cache_hits"] += 1

        if row["analysis_source"] == "cached":
            metrics["content_cache_hits"] += 1
            metrics["api_calls_saved"] += 1
            metrics["embeddings_reused"] += 1

        t = row["ocr_processing_time_ms"] or 0
        pages = row["ocr_pages_processed"] or 0
        if pages > 0 and t > 0:
            ocr_times.append(t)

    if ocr_times:
        metrics["avg_ocr_time_ms"] = round(sum(ocr_times) / len(ocr_times), 1)

    return metrics


# ---------------------------------------------------------------------------
# Search History (Phase 3)
# ---------------------------------------------------------------------------

def log_search_query(query: str, result_count: int) -> None:
    """Log a user search query for analytics and autocomplete."""
    now = _now()
    conn = _connect()
    with conn:
        conn.execute(
            """
            INSERT INTO search_history (query, result_count, searched_at)
            VALUES (?, ?, ?)
            """,
            (query, result_count, now),
        )


def get_recent_searches(limit: int = 10) -> list[dict]:
    """Retrieve recent unique searches for autocomplete suggestions."""
    conn = _connect()
    with conn:
        rows = conn.execute(
            """
            SELECT query, MAX(searched_at) as last_searched
            FROM search_history
            GROUP BY query
            ORDER BY last_searched DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return _rows_to_dicts(rows)

def log_search_click(query: str, document_id: int, position: Optional[int] = None) -> None:
    """Log when a user clicks a document in search results."""
    now = _now()
    conn = _connect()
    with conn:
        conn.execute(
            """
            INSERT INTO search_clicks (query, document_id, position, clicked_at)
            VALUES (?, ?, ?, ?)
            """,
            (query, document_id, position, now),
        )
