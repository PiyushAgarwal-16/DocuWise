"""
core/scanner.py — Filesystem discovery and change detection for DocuWise.

Responsibilities:
  - Recursively walk a root folder.
  - Filter files by supported extension and ignore rules.
  - Detect new files, changed files, and unchanged files.
  - Sync discovery results into the database (no text extraction here).
  - Record scan sessions for audit purposes.

This module does NOT perform:
  - Text extraction
  - Embedding generation
  - Gemini API calls
  - Duplicate detection
  - Any UI interaction
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import SUPPORTED_EXTENSIONS, TIMESTAMP_FORMAT
from core.database import (
    complete_scan_session,
    document_exists,
    get_all_documents,
    insert_document,
    start_scan_session,
    update_document_status,
    _connect,
    _now,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Folders and file prefixes that are always skipped during traversal.
# These are matched against individual path component names (case-insensitive
# on Windows, case-sensitive on Linux/macOS — normalised to lowercase below).
# ---------------------------------------------------------------------------
_IGNORED_FOLDER_NAMES: frozenset[str] = frozenset({
    "__pycache__",
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "venv",
    ".venv",
    "env",
    ".env",
    "site-packages",
    ".idea",
    ".vscode",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
})


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_ignored_path(path: Path) -> bool:
    """
    Return True if *path* (file or directory) should be skipped entirely.

    A path is ignored when any of the following are true:
      - Any component of the path matches a known system/tool folder name.
      - The file or folder name starts with a dot (hidden on Unix-like systems).
      - The file or folder name starts with '~$' (Microsoft Office lock files).

    Args:
        path: Absolute or relative Path object to evaluate.

    Returns:
        True if the path should be skipped, False if it should be processed.
    """
    for part in path.parts:
        part_lower = part.lower()

        # Hidden files and folders (dot-prefix), but allow the drive root on Windows.
        if part.startswith(".") and len(part) > 1:
            return True

        # Microsoft Office temporary lock files.
        if part.startswith("~$"):
            return True

        # Named system / tool directories.
        if part_lower in _IGNORED_FOLDER_NAMES:
            return True

    return False


def is_supported_file(path: Path) -> bool:
    """
    Return True if *path* is a regular file with a supported extension.

    The check is case-insensitive so that '.PDF' and '.pdf' are both accepted.
    The path must also pass the is_ignored_path() filter.

    Args:
        path: Path object pointing to a file to evaluate.

    Returns:
        True if the file should be indexed by DocuWise, False otherwise.
    """
    if not path.is_file():
        return False

    if is_ignored_path(path):
        return False

    return path.suffix.lower() in SUPPORTED_EXTENSIONS


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _stat_timestamps(path: Path) -> tuple[Optional[str], Optional[str]]:
    """
    Read filesystem timestamps from *path* using os.stat().

    Returns:
        Tuple of (file_created_at, file_modified_at) as UTC ISO-8601 strings,
        or (None, None) if the stat call fails.
    """
    try:
        stat = path.stat()
        fmt = TIMESTAMP_FORMAT

        created = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).strftime(fmt)
        modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime(fmt)
        return created, modified
    except OSError as exc:
        logger.warning("Could not stat '%s': %s", path, exc)
        return None, None


def _file_size_kb(path: Path) -> float:
    """
    Return the size of *path* in kilobytes, rounded to 2 decimal places.
    Returns 0.0 if the stat call fails.
    """
    try:
        return round(path.stat().st_size / 1024, 2)
    except OSError:
        return 0.0


def _get_stored_modified_at(file_path: str) -> Optional[str]:
    """
    Fetch the stored file_modified_at timestamp for an existing document row.

    Returns None if the document does not exist or has no stored timestamp.

    Args:
        file_path: Absolute path string used as the unique key in the DB.

    Returns:
        ISO-8601 timestamp string or None.
    """
    try:
        conn = _connect()
        with conn:
            row = conn.execute(
                "SELECT file_modified_at FROM documents WHERE file_path = ? LIMIT 1",
                (file_path,),
            ).fetchone()
        return row["file_modified_at"] if row else None
    except sqlite3.Error as exc:
        logger.error("DB read failed for '%s': %s", file_path, exc)
        return None


def _update_last_scanned_at(file_path: str) -> None:
    """
    Refresh the last_scanned_at timestamp for an unchanged document.

    This is the only write operation performed for files that have not
    changed since the previous scan — it keeps the staleness detection
    logic accurate without triggering a full reprocess.

    Args:
        file_path: Absolute path string identifying the document row.
    """
    try:
        conn = _connect()
        with conn:
            conn.execute(
                "UPDATE documents SET last_scanned_at = ?, updated_at = ? WHERE file_path = ?",
                (_now(), _now(), file_path),
            )
    except sqlite3.Error as exc:
        logger.error("Failed to update last_scanned_at for '%s': %s", file_path, exc)


def _update_file_stats(
    file_path: str,
    file_size_kb: float,
    file_created_at: Optional[str],
    file_modified_at: Optional[str],
) -> None:
    """
    Persist refreshed filesystem metadata for a changed document.

    Called after update_document_status('pending') to ensure the stored
    timestamps reflect the current state of the file on disk.

    Args:
        file_path:        Absolute path string identifying the document row.
        file_size_kb:     New file size in kilobytes.
        file_created_at:  UTC ISO-8601 creation timestamp from os.stat().
        file_modified_at: UTC ISO-8601 modification timestamp from os.stat().
    """
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                UPDATE documents
                   SET file_size_kb      = ?,
                       file_created_at   = ?,
                       file_modified_at  = ?,
                       last_scanned_at   = ?,
                       updated_at        = ?
                 WHERE file_path = ?
                """,
                (
                    file_size_kb,
                    file_created_at,
                    file_modified_at,
                    _now(),
                    _now(),
                    file_path,
                ),
            )
    except sqlite3.Error as exc:
        logger.error("Failed to update file stats for '%s': %s", file_path, exc)


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def scan_folder(root_folder: str) -> dict:
    """
    Recursively scan *root_folder* and sync results into the database.

    Processing logic per discovered file:
      - New file (not in DB)    → insert_document() with status='pending'
      - Existing, unchanged     → update last_scanned_at only (no reprocess)
      - Existing, modified      → reset to status='pending', refresh file stats
      - Stat/permission failure → counted as failed, logged, skipped

    Ignored automatically:
      - Hidden files and folders (dot-prefix)
      - System folders: __pycache__, .git, node_modules, venv, etc.
      - Microsoft Office lock files (~$ prefix)
      - Files with unsupported extensions

    A scan_session row is created at the start and completed at the end,
    providing an audit trail of every scan run.

    Args:
        root_folder: Absolute path to the folder to scan. Must exist.

    Returns:
        A summary dict with the following keys:
        {
            "session_id":      int,   # scan_sessions.id for this run
            "total_files":     int,   # supported files discovered
            "new_files":       int,   # files inserted for the first time
            "changed_files":   int,   # existing files reset to pending
            "unchanged_files": int,   # files with no detected changes
            "failed_files":    int,   # files that could not be processed
        }

    Raises:
        ValueError: If root_folder does not exist or is not a directory.
    """
    root = Path(root_folder).resolve()

    if not root.exists():
        raise ValueError(f"Scan target does not exist: '{root_folder}'")
    if not root.is_dir():
        raise ValueError(f"Scan target is not a directory: '{root_folder}'")

    logger.info("Starting scan of '%s'", root)
    session_id = start_scan_session(str(root))

    counters = {
        "session_id":      session_id,
        "total_files":     0,
        "new_files":       0,
        "changed_files":   0,
        "unchanged_files": 0,
        "failed_files":    0,
    }

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        current_dir = Path(dirpath)

        # ── Prune ignored directories in-place so os.walk won't descend ──────
        # Modifying dirnames[:] prevents os.walk from recursing into them.
        dirnames[:] = [
            d for d in dirnames
            if not is_ignored_path(current_dir / d)
        ]

        for filename in filenames:
            file_path = current_dir / filename

            # Skip files that fail the extension or ignore checks.
            if not is_supported_file(file_path):
                continue

            counters["total_files"] += 1
            _process_file(file_path, counters)

    complete_scan_session(
        session_id=session_id,
        total_files=counters["total_files"],
        processed_files=counters["new_files"] + counters["changed_files"] + counters["unchanged_files"],
        failed_files=counters["failed_files"],
    )

    logger.info(
        "Scan complete — total=%d  new=%d  changed=%d  unchanged=%d  failed=%d",
        counters["total_files"],
        counters["new_files"],
        counters["changed_files"],
        counters["unchanged_files"],
        counters["failed_files"],
    )

    return counters


# ---------------------------------------------------------------------------
# Internal per-file processing
# ---------------------------------------------------------------------------

def _process_file(file_path: Path, counters: dict) -> None:
    """
    Determine the appropriate database action for a single discovered file
    and execute it, updating *counters* in place.

    Args:
        file_path: Absolute Path to the discovered file.
        counters:  Mutable counter dict from scan_folder(). Updated in place.
    """
    abs_path = str(file_path)

    # Read filesystem metadata — treat stat failure as a hard failure.
    file_created_at, file_modified_at = _stat_timestamps(file_path)
    if file_modified_at is None:
        logger.warning("Skipping '%s' — could not read filesystem metadata.", file_path)
        counters["failed_files"] += 1
        return

    file_size_kb = _file_size_kb(file_path)
    filename = file_path.name
    extension = file_path.suffix.lower()

    try:
        if not document_exists(abs_path):
            # ── New file: insert a fresh pending record ────────────────────
            insert_document(
                file_path=abs_path,
                filename=filename,
                extension=extension,
                file_size_kb=file_size_kb,
                file_created_at=file_created_at,
                file_modified_at=file_modified_at,
            )
            counters["new_files"] += 1
            logger.debug("New file indexed: '%s'", abs_path)

        else:
            # ── Existing file: compare modification timestamps ─────────────
            stored_modified = _get_stored_modified_at(abs_path)

            if stored_modified != file_modified_at:
                # File has changed — reset to pending so the full pipeline reruns.
                update_document_status(abs_path, "pending")
                _update_file_stats(abs_path, file_size_kb, file_created_at, file_modified_at)
                counters["changed_files"] += 1
                logger.debug("Changed file reset to pending: '%s'", abs_path)

            else:
                # File is unchanged — just refresh the last_scanned_at timestamp.
                _update_last_scanned_at(abs_path)
                counters["unchanged_files"] += 1
                logger.debug("Unchanged file: '%s'", abs_path)

    except sqlite3.Error as exc:
        logger.error("Database error processing '%s': %s", abs_path, exc)
        counters["failed_files"] += 1
    except Exception as exc:  # noqa: BLE001 — catch-all to keep the scan alive
        logger.error("Unexpected error processing '%s': %s", abs_path, exc)
        counters["failed_files"] += 1
