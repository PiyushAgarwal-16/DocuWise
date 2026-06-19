# =============================================================================
# config.py — Central configuration for DocuWise V1
#
# This is the single source of truth for all application constants.
# Every other module imports from here. No functions, classes, or
# execution code belong in this file.
# =============================================================================

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# =============================================================================
# 1. LLM PROVIDER CONFIGURATION
# =============================================================================

# Active LLM provider. Supported values:
#   "nvidia"  — NVIDIA NIM API (primary, OpenAI-compatible)
#   "gemini"  — Google Gemini (secondary)
# If the selected provider fails to initialise, HeuristicProvider is used
# as a last-resort fallback so no document is permanently blocked.
LLM_PROVIDER: str = "nvidia"

# Sampling temperature shared by all providers.
# 0.1 = very deterministic — preferred for structured JSON output.
LLM_TEMPERATURE: float = 0.1


# =============================================================================
# 2. NVIDIA NIM CONFIGURATION
# =============================================================================

# NVIDIA NIM API key. Obtain from https://build.nvidia.com/
NVIDIA_API_KEY: str = os.environ.get("NVIDIA_API_KEY", "")

# Base URL for the NVIDIA NIM OpenAI-compatible endpoint.
NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

# Model to use for document analysis.
# Alternatives: meta/llama-3.1-70b-instruct, mistralai/mistral-7b-instruct-v0.3
NVIDIA_MODEL: str = "meta/llama-3.1-8b-instruct"

# Mandatory minimum delay (seconds) between consecutive NVIDIA API calls.
# Keeps request cadence well under the per-minute quota.
NVIDIA_REQUEST_DELAY_SECONDS: float = 5.0

# Hard rate-limit ceilings. The rate limiter enforces these before every call.
NVIDIA_MAX_REQUESTS_PER_MINUTE: int = 10
NVIDIA_MAX_REQUESTS_PER_HOUR: int = 300

# Per-scan budget cap. Once this many LLM requests have been made in a single
# scan run, all remaining unanalyzed documents are left at 'pending' and
# the pipeline logs "LLM request budget exhausted".
MAX_LLM_REQUESTS_PER_SCAN: int = 100

# Feature flags — can be toggled without touching code.
ENABLE_LLM_ANALYSIS: bool = True       # Set False to use only heuristic fallback.
ENABLE_FALLBACK_ANALYSIS: bool = True  # Allow heuristic analyzer when LLM fails.
ENABLE_ANALYSIS_CACHE: bool = True     # Skip LLM for already-analyzed unchanged docs.



# =============================================================================
# 3. GEMINI CONFIGURATION (secondary provider / legacy)
# =============================================================================

# Your Google Gemini API key. Obtain from https://aistudio.google.com/
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")

# Gemini model used when LLM_PROVIDER = "gemini".
# Confirmed available models (run validate_model() in analyzer.py to list all):
#   gemini-2.0-flash       — stable, fast, free-tier friendly  <- recommended
#   gemini-2.5-flash       — best quality, slightly slower
#   gemini-2.0-flash-lite  — fastest, lowest cost
GEMINI_MODEL: str = "gemini-2.0-flash"

# Maximum number of tokens Gemini is allowed to return per response.
GEMINI_MAX_OUTPUT_TOKENS: int = 1024

# Temperature for Gemini (kept for backward compatibility; LLM_TEMPERATURE is preferred).
GEMINI_TEMPERATURE: float = 0.2



# =============================================================================
# 2. DATABASE CONFIGURATION
# =============================================================================

# Path to the SQLite database file, relative to the project root.
# The storage/ directory is created automatically by database.init_db().
DB_PATH: str = "storage/docuwise.db"

# SQLite journal mode. WAL (Write-Ahead Logging) allows concurrent reads
# during writes — important for background processing threads.
DB_JOURNAL_MODE: str = "WAL"

# Timeout in seconds before SQLite raises an OperationalError on a locked DB.
DB_TIMEOUT_SECONDS: float = 10.0

# UTC ISO-8601 timestamp format used consistently across all database writes.
# Example: "2024-03-15T09:30:00.123456"
TIMESTAMP_FORMAT: str = "%Y-%m-%dT%H:%M:%S.%f"


# =============================================================================
# 3. EMBEDDING CONFIGURATION
# =============================================================================

# Root directory for all generated artifacts (DB, embeddings).
STORAGE_DIR: str = "storage"

# Directory where per-document NumPy embedding files are stored.
# Each file is named {document_id}.npy where document_id is the
# integer primary key from the documents table.
EMBEDDINGS_DIR: str = "storage/embeddings"

# Sentence-transformer model used to generate document embedding vectors.
# all-MiniLM-L6-v2: 384-dimensional, fast, excellent semantic quality.
# Downloaded automatically by sentence-transformers on first use (~90 MB).
EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

# Dimensionality of vectors produced by EMBEDDING_MODEL.
# Must match the chosen model. Update if switching models.
EMBEDDING_DIMENSION: int = 384


# =============================================================================
# 4. RELATIONSHIP DETECTION CONFIGURATION
# =============================================================================

# Cosine similarity at or above this value → documents classified as DUPLICATE.
# Range: 0.0–1.0. Applies to embedding-based comparison.
SIMILARITY_THRESHOLD: float = 0.88

# Cosine similarity at or above this value (but below SIMILARITY_THRESHOLD)
# → documents classified as SIMILAR.
NEAR_DUPLICATE_THRESHOLD: float = 0.75

# Set True to log every pairwise score and print the top-20 highest similarity
# pairs at the end of duplicate detection. Useful for threshold tuning.
# Disable in production to avoid flooding logs.
DEBUG_DUPLICATES: bool = True


# Cosine similarity at or above this value, combined with a filename version
# heuristic (e.g. v1/v2, date suffix), → classified as NEWER_VERSION.
VERSION_THRESHOLD: float = 0.90

# Filename substrings used to detect version chains (case-insensitive match).
# If two similar documents share these patterns, they are likely version chains.
VERSION_FILENAME_PATTERNS: list[str] = [
    "v1", "v2", "v3", "v4", "v5",
    "draft", "final", "revised", "updated",
    "_old", "_backup", "_copy",
]

# Number of documents processed per batch during relationship detection.
# Larger batches are faster but use more RAM for the similarity matrix.
RELATIONSHIP_BATCH_SIZE: int = 500


# =============================================================================
# 5. PROCESSING CONFIGURATION
# =============================================================================

# Maximum number of characters from extracted text sent to Gemini.
# Text longer than this is truncated from the end before the API call.
# 3000 chars ≈ ~500–600 words — sufficient for category/summary extraction.
MAX_TEXT_CHARS_FOR_LLM: int = 3000

# Minimum word count for a document to be considered content-rich.
# Files below this threshold are flagged as "low content" in the UI.
MIN_WORD_COUNT: int = 50

# Delay in seconds between consecutive Gemini API calls.
# Prevents hitting the free-tier rate limit (60 RPM on gemini-2.5-flash).
API_CALL_DELAY_SECONDS: float = 1.0

# Maximum number of times a failed API call is retried before the document
# is marked as processing_status = 'failed'.
MAX_RETRY_ATTEMPTS: int = 3

# Base delay in seconds between retries. Applied with exponential backoff:
# attempt 1 → 2.0s, attempt 2 → 4.0s, attempt 3 → 8.0s.
RETRY_BACKOFF_SECONDS: float = 2.0

# Number of documents processed per scan batch before writing progress to DB.
# Smaller = more frequent UI updates. Larger = fewer DB round-trips.
SCAN_BATCH_SIZE: int = 50

# If True, files whose file_modified_at matches the stored value are skipped
# entirely — no re-extraction, re-embedding, or re-analysis occurs.
SKIP_UNCHANGED_FILES: bool = True


# =============================================================================
# 6. FILE SCANNING CONFIGURATION
# =============================================================================

# File extensions that DocuWise will discover and process.
# All comparisons are case-insensitive (handled in scanner.py).
SUPPORTED_EXTENSIONS: list[str] = [
    ".pdf",
    ".docx",
    ".txt",
    ".pptx",
    ".xlsx",
]

# Filename substrings that identify junk or low-value files (case-insensitive).
# Files matching any pattern are flagged but NOT automatically deleted.
JUNK_FILENAME_PATTERNS: list[str] = [
    "~$",           # Microsoft Office temporary lock files
    "copy of",      # Files created via "copy" operation
    "draft",        # Explicit draft versions
    "untitled",     # Files never properly named
    "new document", # Default Office document name
    "temp",         # Temporary files
    "tmp",          # Temporary files (abbreviated)
]

# Default document categories used as the valid set for Gemini classification.
# Also shown as filter options in the UI.
DEFAULT_CATEGORIES: list[str] = [
    "Academic",
    "Work",
    "Finance",
    "Legal",
    "Personal",
    "Technical",
    "Miscellaneous",
]

# Category weights used by insight_engine.py when computing importance scores.
# Higher weight = documents in this category score higher for "likely_keep".
CATEGORY_IMPORTANCE_WEIGHTS: dict[str, float] = {
    "Legal":         1.0,
    "Finance":       0.9,
    "Work":          0.8,
    "Academic":      0.75,
    "Technical":     0.7,
    "Personal":      0.6,
    "Miscellaneous": 0.4,
}


# =============================================================================
# 7. RULE ENGINE CONFIGURATION
# =============================================================================

# Supported actions a user rule can trigger.
# These are the only valid values for user_rules.action in the database.
RULE_ACTIONS: list[str] = [
    "highlight",          # Mark document with a color in the UI
    "suggest_deletion",   # Set deletion_candidate = 1
    "mark_important",     # Set likely_keep = 1 and boost importance_score
    "tag",                # Append tags to document_insights.tags_json
]

# Supported relationship types stored in document_relationships.relationship_type.
RELATIONSHIP_TYPES: list[str] = [
    "duplicate",
    "similar",
    "newer_version",
    "related",
]

# Valid processing status values for documents.processing_status.
# These are the only states the processing state machine may write.
PROCESSING_STATUSES: list[str] = [
    "pending",     # Discovered but not yet processed
    "extracted",   # Text extracted successfully
    "image_only",  # PDF with no extractable text (image-based); OCR not enabled
    "embedded",    # Embedding vector generated and saved
    "analyzed",    # Gemini analysis complete
    "completed",   # All pipeline stages done (rules evaluated, insights generated)
    "failed",      # One or more stages failed; see error_message
]

# Maximum number of tags the insight engine may generate per document.
MAX_TAGS_PER_DOCUMENT: int = 8

# Documents with importance_score below this value have likely_keep set to 0.
IMPORTANCE_SCORE_THRESHOLD: float = 0.40


# =============================================================================
# 8. CONFIDENCE SCORE CONFIGURATION
# =============================================================================

# AI-generated results with confidence below this value trigger a UI warning badge.
# Applies to: category_confidence, summary_confidence, importance_confidence.
LOW_CONFIDENCE_THRESHOLD: float = 0.60

# Results at or above this value are considered high-confidence and displayed
# without any uncertainty indicator in the UI.
HIGH_CONFIDENCE_THRESHOLD: float = 0.80

# Fallback confidence assigned when Gemini omits a confidence field.
# Represents neutral/unknown certainty — not high, not low.
DEFAULT_CONFIDENCE_FALLBACK: float = 0.50

# Fixed confidence score assigned to relationships detected via exact MD5 match.
MD5_MATCH_CONFIDENCE: float = 1.00

# Fixed confidence score assigned to relationships detected by filename heuristic only.
FILENAME_HEURISTIC_CONFIDENCE: float = 0.65


# =============================================================================
# 9. OCR CONFIGURATION  (future support — not active in V1)
# =============================================================================

# Master switch for OCR processing. Set to True once an OCR backend is integrated.
# When False, files in OCR_EXTENSIONS are skipped entirely during extraction.
OCR_ENABLED: bool = False

# File extensions that will be routed to the OCR pipeline when OCR_ENABLED = True.
# These are image-based formats that cannot be read by standard text extractors.
OCR_EXTENSIONS: list[str] = [
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".bmp",
]

# OCR engine to use when OCR_ENABLED = True.
# Supported future values: "tesseract" | "easyocr" | "gemini_vision"
OCR_ENGINE: str = "tesseract"

# Minimum OCR confidence score (0–100 for Tesseract) below which extracted
# text is discarded as unreliable.
OCR_MIN_CONFIDENCE: int = 60


# =============================================================================
# 10. LOGGING CONFIGURATION
# =============================================================================

# Logging level for the application logger.
# Values: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL"
LOG_LEVEL: str = "INFO"

# Path to the log file, relative to the project root.
# Set to empty string "" to disable file logging (console only).
LOG_FILE_PATH: str = "storage/docuwise.log"

# Maximum size of a single log file in bytes before rotation occurs (5 MB).
LOG_MAX_BYTES: int = 5 * 1024 * 1024

# Number of rotated log file backups to retain alongside the active log file.
LOG_BACKUP_COUNT: int = 3

# Log line format. Includes timestamp, level, module name, and message.
LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


# =============================================================================
# 11. UI DEFAULTS
# =============================================================================

# Available highlight colors for user rules. Keys are display names; values
# are hex color strings used directly in PyQt6 stylesheet rules.
HIGHLIGHT_COLORS: dict[str, str] = {
    "Red":    "#FF4C4C",
    "Yellow": "#FFD700",
    "Green":  "#4CAF50",
    "Blue":   "#4A90D9",
    "Purple": "#9B59B6",
    "Orange": "#FF8C00",
}

# Default highlight color applied to new rules if the user does not specify one.
DEFAULT_HIGHLIGHT_COLOR: str = "Yellow"

# Maximum number of characters shown in the document summary preview inside
# the document table. Longer summaries are truncated with an ellipsis.
SUMMARY_PREVIEW_LENGTH: int = 120

# Number of document rows loaded per page in the main document table.
# Prevents UI lag when the corpus is large.
TABLE_PAGE_SIZE: int = 100

# Application window title shown in the OS taskbar and title bar.
APP_TITLE: str = "DocuWise — Document Intelligence"

# Default width and height of the main application window in pixels.
DEFAULT_WINDOW_WIDTH: int = 1280
DEFAULT_WINDOW_HEIGHT: int = 800
