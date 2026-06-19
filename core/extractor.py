"""
core/extractor.py — Text extraction layer for DocuWise.

Responsibilities:
  - Extract plain text from PDF, DOCX, and TXT files.
  - Compute MD5 hash of the raw file bytes for duplicate detection.
  - Count words in extracted text.
  - Persist results to the database via update_document_extraction().
  - Set processing_status to 'extracted' on success or 'failed' on error.

This module does NOT perform:
  - OCR (image-based text recognition)
  - PPTX / XLSX extraction (planned for V2)
  - Gemini API calls
  - Embedding generation
  - Any UI interaction
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from docx import Document as DocxDocument

from config import MIN_WORD_COUNT
from core.database import update_document_extraction, update_document_status

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ExtractedDocument:
    """
    Structured result returned by extract_document() and all format-specific
    extractor functions.

    Attributes:
        file_path:     Absolute path to the source file.
        text:          Full plain-text content extracted from the document.
                       Empty string on failure.
        word_count:    Number of whitespace-delimited tokens in *text*.
        page_count:    Number of pages (PDF only). None for DOCX and TXT.
        success:       True if extraction completed without a fatal error.
        error_message: Human-readable description of the failure, or None.
    """
    file_path: str
    text: str = ""
    word_count: int = 0
    page_count: Optional[int] = None
    success: bool = False
    image_only: bool = False          # True when PDF extracted OK but has zero text (scanned image)
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# MD5 helper
# ---------------------------------------------------------------------------

def compute_md5(file_path: str) -> str:
    """
    Compute the MD5 hex-digest of the raw bytes of a file.

    Reads the file in 64 KB chunks to avoid loading large files into memory
    all at once. Used by the relationship detector to find exact duplicates
    without comparing embedding vectors.

    Args:
        file_path: Absolute path to the file.

    Returns:
        Lowercase hex-digest string (32 characters), e.g. 'a1b2c3d4...'.

    Raises:
        OSError: If the file cannot be opened or read.
    """
    hasher = hashlib.md5()
    chunk_size = 65_536  # 64 KB

    with open(file_path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            hasher.update(chunk)

    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Word count helper
# ---------------------------------------------------------------------------

def _count_words(text: str) -> int:
    """
    Count the number of words in *text* using a whitespace-split approach.

    Strips leading/trailing whitespace and splits on any whitespace sequence.
    Returns 0 for empty or whitespace-only strings.

    Args:
        text: Plain-text string to count words in.

    Returns:
        Integer word count.
    """
    stripped = text.strip()
    if not stripped:
        return 0
    return len(re.split(r"\s+", stripped))


# ---------------------------------------------------------------------------
# Format-specific extractors
# ---------------------------------------------------------------------------

def extract_pdf(file_path: str) -> ExtractedDocument:
    """
    Extract plain text from a PDF file using PyMuPDF (fitz).

    Pages are processed in order; text from each page is joined with a
    double newline to preserve visual separation. Encrypted PDFs that
    cannot be opened with an empty password are treated as failures
    rather than raising an unhandled exception.

    Args:
        file_path: Absolute path to the PDF file.

    Returns:
        ExtractedDocument with text, word_count, and page_count populated
        on success, or success=False and error_message set on failure.
    """
    try:
        doc = fitz.open(file_path)

        # Attempt to unlock encrypted PDFs with an empty password.
        if doc.is_encrypted:
            if not doc.authenticate(""):
                doc.close()
                return ExtractedDocument(
                    file_path=file_path,
                    success=False,
                    error_message="PDF is encrypted and password-protected.",
                )

        page_texts: list[str] = []
        for page in doc:
            page_text = page.get_text("text")  # plain text mode
            if page_text:
                page_texts.append(page_text.strip())

        page_count = len(doc)
        doc.close()

        full_text = "\n\n".join(page_texts)
        word_count = _count_words(full_text)

        logger.debug(
            "PDF extracted: '%s' | pages=%d | words=%d",
            file_path, page_count, word_count,
        )

        return ExtractedDocument(
            file_path=file_path,
            text=full_text,
            word_count=word_count,
            page_count=page_count,
            success=True,
        )

    except fitz.FileDataError as exc:
        msg = f"Corrupt or unreadable PDF: {exc}"
        logger.warning("PDF extraction failed for '%s': %s", file_path, msg)
        return ExtractedDocument(file_path=file_path, success=False, error_message=msg)

    except Exception as exc:  # noqa: BLE001
        msg = f"Unexpected PDF extraction error: {exc}"
        logger.error("PDF extraction failed for '%s': %s", file_path, exc, exc_info=True)
        return ExtractedDocument(file_path=file_path, success=False, error_message=msg)


def extract_docx(file_path: str) -> ExtractedDocument:
    """
    Extract plain text from a DOCX file using python-docx.

    All paragraphs are collected in document order and joined with newlines.
    Tables and headers inside the main document body are included via the
    paragraph-level iteration that python-docx exposes. Embedded images,
    charts, and macros are ignored.

    Args:
        file_path: Absolute path to the DOCX file.

    Returns:
        ExtractedDocument with text and word_count populated on success,
        or success=False and error_message set on failure.
        page_count is always None (DOCX has no native page count API).
    """
    try:
        docx = DocxDocument(file_path)

        paragraphs: list[str] = []
        for para in docx.paragraphs:
            stripped = para.text.strip()
            if stripped:
                paragraphs.append(stripped)

        full_text = "\n".join(paragraphs)
        word_count = _count_words(full_text)

        logger.debug(
            "DOCX extracted: '%s' | paragraphs=%d | words=%d",
            file_path, len(paragraphs), word_count,
        )

        return ExtractedDocument(
            file_path=file_path,
            text=full_text,
            word_count=word_count,
            page_count=None,
            success=True,
        )

    except Exception as exc:  # noqa: BLE001
        msg = f"DOCX extraction error: {exc}"
        logger.error("DOCX extraction failed for '%s': %s", file_path, exc, exc_info=True)
        return ExtractedDocument(file_path=file_path, success=False, error_message=msg)


def extract_txt(file_path: str) -> ExtractedDocument:
    """
    Extract plain text from a TXT file with encoding fallback.

    Attempts UTF-8 first (covers the vast majority of modern text files).
    Falls back to latin-1 (ISO-8859-1) which maps every byte to a valid
    character and therefore never raises a UnicodeDecodeError — making it
    a safe last resort for legacy or mixed-encoding files.

    Args:
        file_path: Absolute path to the plain-text file.

    Returns:
        ExtractedDocument with text and word_count populated on success,
        or success=False and error_message set on failure.
        page_count is always None for TXT files.
    """
    encodings = ["utf-8", "latin-1"]

    for encoding in encodings:
        try:
            with open(file_path, "r", encoding=encoding, errors="replace") as fh:
                full_text = fh.read()

            word_count = _count_words(full_text)

            logger.debug(
                "TXT extracted: '%s' | encoding=%s | words=%d",
                file_path, encoding, word_count,
            )

            return ExtractedDocument(
                file_path=file_path,
                text=full_text,
                word_count=word_count,
                page_count=None,
                success=True,
            )

        except UnicodeDecodeError:
            logger.debug("Encoding '%s' failed for '%s', trying next.", encoding, file_path)
            continue

        except OSError as exc:
            msg = f"Could not read TXT file: {exc}"
            logger.error("TXT extraction failed for '%s': %s", file_path, exc)
            return ExtractedDocument(file_path=file_path, success=False, error_message=msg)

    # All encodings exhausted (should not normally occur given latin-1 fallback).
    msg = "All encoding attempts failed."
    logger.error("TXT extraction failed for '%s': %s", file_path, msg)
    return ExtractedDocument(file_path=file_path, success=False, error_message=msg)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

# Maps lowercase file extensions to the appropriate extractor function.
# Extend this dict to add PPTX / XLSX support in V2.
_EXTRACTOR_MAP = {
    ".pdf":  extract_pdf,
    ".docx": extract_docx,
    ".txt":  extract_txt,
}


def extract_document(file_path: str) -> ExtractedDocument:
    """
    Dispatch to the correct format-specific extractor based on file extension.

    This is the primary entry point for single-document extraction. It does
    not write to the database — use process_document() for the full
    extract → hash → persist workflow.

    Args:
        file_path: Absolute path to the document to extract.

    Returns:
        ExtractedDocument. success=False if the extension is unsupported
        or the file does not exist.
    """
    path = Path(file_path)

    if not path.exists():
        return ExtractedDocument(
            file_path=file_path,
            success=False,
            error_message=f"File not found: '{file_path}'",
        )

    if not path.is_file():
        return ExtractedDocument(
            file_path=file_path,
            success=False,
            error_message=f"Path is not a regular file: '{file_path}'",
        )

    extension = path.suffix.lower()
    extractor_fn = _EXTRACTOR_MAP.get(extension)

    if extractor_fn is None:
        return ExtractedDocument(
            file_path=file_path,
            success=False,
            error_message=f"Unsupported file extension: '{extension}'",
        )

    return extractor_fn(file_path)


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------

def process_document(file_path: str) -> ExtractedDocument:
    """
    Full extraction workflow for a single document.

    Steps:
      1. Extract plain text via extract_document().
      2. Compute MD5 hash of the raw file bytes.
      3. Persist word_count, md5_hash, and extracted_text to the database.
      4. Set processing_status:
           - 'extracted' on success (even for low word-count files — the
              analyzer will flag them separately using MIN_WORD_COUNT).
           - 'failed'    on extraction or hashing error.

    This function is called by the processing pipeline coordinator for
    every document with processing_status = 'pending'. It is safe to call
    repeatedly — database writes are idempotent for the same file_path.

    Args:
        file_path: Absolute path to the document to process.

    Returns:
        The ExtractedDocument result. Callers can inspect .success and
        .error_message to decide how to proceed.
    """
    logger.info("Processing: '%s'", file_path)

    # ── Step 1: Extract text ─────────────────────────────────────────────────
    result = extract_document(file_path)

    if not result.success:
        logger.warning("Extraction failed for '%s': %s", file_path, result.error_message)
        update_document_status(file_path, "failed", error_message=result.error_message)
        return result

    # ── Step 2: Compute MD5 hash ─────────────────────────────────────────────
    try:
        md5_hash = compute_md5(file_path)
    except OSError as exc:
        msg = f"MD5 computation failed: {exc}"
        logger.error("Hashing failed for '%s': %s", file_path, exc)
        result.success = False
        result.error_message = msg
        update_document_status(file_path, "failed", error_message=msg)
        return result

    # ── Step 3: Detect image-only PDFs ───────────────────────────────────────
    # A PDF that opens without error but yields zero words is an image-based
    # scan. We record the MD5 (useful for exact-duplicate detection later) and
    # set a dedicated status so the pipeline skips Gemini and embedding stages.
    if result.word_count == 0:
        image_only_msg = "Image-based PDF detected. OCR not enabled."
        logger.info(
            "Image-only document: '%s' | pages=%s",
            Path(file_path).name,
            result.page_count,
        )
        try:
            update_document_extraction(
                file_path=file_path,
                word_count=0,
                md5_hash=md5_hash,
                extracted_text="",
            )
            update_document_status(file_path, "image_only", error_message=image_only_msg)
        except Exception as exc:  # noqa: BLE001
            logger.error("DB write failed for image-only '%s': %s", file_path, exc)
        result.image_only = True
        return result

    # ── Step 4: Persist and advance status ───────────────────────────────────
    try:
        update_document_extraction(
            file_path=file_path,
            word_count=result.word_count,
            md5_hash=md5_hash,
            extracted_text=result.text,
        )
        logger.info(
            "Extracted '%s' | words=%d | md5=%s...",
            Path(file_path).name, result.word_count, md5_hash[:8],
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"Database write failed after extraction: {exc}"
        logger.error("DB write failed for '%s': %s", file_path, exc, exc_info=True)
        result.success = False
        result.error_message = msg
        update_document_status(file_path, "failed", error_message=msg)
        return result

    return result
