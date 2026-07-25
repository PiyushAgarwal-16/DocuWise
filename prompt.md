You are a senior Python software architect specializing in document intelligence systems, OCR, AI pipelines, desktop applications, and scalable software architecture.

Project

DocuWise

Technology Stack

Frontend
- React
- Tauri

Backend
- Python 3.12
- SQLite
- NVIDIA API
- Sentence Transformers
- PyMuPDF
- python-docx
- python-pptx
- openpyxl

Current Pipeline

Folder Scan
↓

Native Text Extraction
↓

NVIDIA Analysis
↓

Embedding Generation
↓

Duplicate Detection
↓

SQLite

The backend is already functional.

The objective is to integrate a production-quality OCR system and redesign the extraction pipeline to support long-term scalability while maintaining backward compatibility.

========================================================================
IMPORTANT
========================================================================

DO NOT immediately implement OCR.

First understand the existing architecture.

Analyze:

core/scanner.py

core/extractor.py

core/analyzer.py

core/embedder.py

core/pipeline.py

core/database.py

Determine:

- current extraction flow
- state transitions
- database writes
- database reads
- cache opportunities
- bottlenecks

Produce an implementation plan internally before modifying any code.

Do NOT create duplicate logic.

Integrate into the existing architecture.

========================================================================
PHASE 1 — ARCHITECTURE AUDIT
========================================================================

Document the current pipeline.

Scanner

↓

Extractor

↓

Analyzer

↓

Embedder

↓

Duplicate Detection

↓

Database

Identify:

- extraction entry points
- failure paths
- status transitions
- cache opportunities
- expensive operations

========================================================================
PHASE 2 — CONTENT CACHE LAYER
========================================================================

Do NOT implement only OCR caching.

Instead implement a reusable Content Cache.

Create a new table:

content_cache

Fields:

md5_hash (PRIMARY KEY)

native_text

ocr_text

final_text

extraction_method

embedding_json

summary

category

subject

tags_json

importance_score

analysis_source

ocr_engine

ocr_version

ocr_confidence

ocr_processing_time_ms

ocr_pages_processed

created_at

updated_at

Purpose:

Every expensive operation should only happen once for identical document content.

Workflow:

Generate MD5

↓

Check content_cache

Cache Hit

↓

Reuse:

native_text

OCR text

final text

embedding

summary

category

subject

tags

importance

analysis source

Skip:

OCR

NVIDIA

Embedding generation

Cache Miss

↓

Continue normal extraction pipeline

↓

Populate cache

Future duplicate or moved files should reuse the cached information.

========================================================================
PHASE 3 — OCR ENGINE
========================================================================

Use PaddleOCR.

Do NOT use Tesseract.

Create:

core/ocr.py

Architecture:

BaseOCREngine

PaddleOCREngine

The extraction pipeline should never depend directly on PaddleOCR.

All OCR engines must implement the same interface.

========================================================================
PHASE 4 — HYBRID EXTRACTION
========================================================================

Current:

PDF

↓

PyMuPDF

↓

No text

↓

Image Only

New:

PDF

↓

Native Extraction

↓

Enough text?

YES

↓

Continue

NO

↓

OCR only pages lacking text

↓

Merge:

Native Text

+

OCR Text

↓

Final Extracted Text

↓

Continue pipeline

Never OCR every page.

OCR only pages requiring OCR.

========================================================================
PHASE 5 — IMAGE SUPPORT
========================================================================

Support:

png

jpg

jpeg

bmp

tiff

webp

Images become first-class documents.

Update:

scanner

extractor

pipeline

database

UI

========================================================================
PHASE 6 — EXTRACTION METADATA
========================================================================

Store:

Extraction Method

Values:

native

hybrid

ocr_only

image_only

Store:

OCR Engine

OCR Version

OCR Confidence

Pages OCR'd

Pages Skipped

Processing Time

OCR Cached

These values should be visible inside the UI.

========================================================================
PHASE 7 — CONFIGURATION
========================================================================

Extend config.py

Add:

OCR_ENABLED

OCR_ENGINE

OCR_VERSION

OCR_LANGUAGE

OCR_MIN_TEXT_THRESHOLD

OCR_MIN_CONFIDENCE

OCR_CACHE_ENABLED

OCR_TIMEOUT_SECONDS

OCR_MAX_IMAGE_SIZE

OCR_MAX_PDF_PAGES

CONTENT_CACHE_ENABLED

========================================================================
PHASE 8 — PERFORMANCE
========================================================================

Requirements:

Load PaddleOCR once.

Singleton.

Never recreate OCR model.

Never OCR cached files.

Never OCR pages containing text.

Never regenerate embeddings for cached documents.

Never call NVIDIA when cached analysis exists.

Optimize image conversion.

Optimize PDF rendering.

Minimize memory usage.

========================================================================
PHASE 9 — PIPELINE
========================================================================

New Flow

Scan

↓

Native Extraction

↓

Generate MD5

↓

Content Cache Lookup

↓

Cache Hit?

YES

↓

Restore:

Final Text

Embedding

Summary

Category

Subject

Tags

Importance

Analysis Source

↓

Continue

NO

↓

OCR if required

↓

NVIDIA Analysis

↓

Embedding

↓

Populate Cache

↓

Continue

========================================================================
PHASE 10 — UI
========================================================================

Dashboard

Display:

Native Documents

Hybrid OCR Documents

OCR Only Documents

Image Only Documents

OCR Cache Hits

Content Cache Hits

API Calls Saved

Embeddings Reused

Average OCR Time

Document Details

Display:

Extraction Method

OCR Engine

OCR Confidence

Cache Status

Analysis Source

========================================================================
PHASE 11 — LIVE SCAN EXPERIENCE
========================================================================

During scanning display:

Current File

Current Stage

Current Page

Progress

ETA

Elapsed Time

Files/minute

Possible stages:

Scanning

Native Extraction

Content Cache Lookup

Cache Hit

OCR

Analyzing

Embedding

Duplicate Detection

Saving

========================================================================
PHASE 12 — ERROR HANDLING
========================================================================

OCR failure must never crash scanning.

Handle:

Corrupt PDFs

Encrypted PDFs

Unsupported Images

Timeout

Memory Errors

OCR Model Failure

If OCR fails:

Use native text if available.

Otherwise:

Mark image_only.

Continue scanning.

========================================================================
PHASE 13 — LOGGING
========================================================================

Structured logs:

CONTENT_CACHE_HIT

CONTENT_CACHE_MISS

OCR_STARTED

OCR_PAGE_SKIPPED

OCR_PAGE_COMPLETED

OCR_COMPLETED

OCR_FAILED

NVIDIA_SKIPPED_CACHE

EMBEDDING_SKIPPED_CACHE

Include:

filename

md5

page

duration

confidence

========================================================================
PHASE 14 — TESTING
========================================================================

Create tests for:

Native PDF

Scanned PDF

Mixed PDF

Image

Duplicate Image

Moved File

Copied File

Cache Hit

Cache Miss

Corrupt PDF

Large PDF

Image Only

Verify:

No duplicate OCR

No duplicate NVIDIA calls

No duplicate embeddings

Correct cache restoration

Correct database updates

Correct UI updates

========================================================================
PHASE 15 — FINAL VALIDATION
========================================================================

Verify:

No regressions.

Scanning works.

Incremental scans work.

Moved files work.

Copied files work.

Duplicate detection works.

Embeddings work.

OCR works.

Caching works.

UI displays extraction metadata correctly.

Future upgrades remain possible.

========================================================================
IMPLEMENTATION CONSTRAINTS
========================================================================

Do not rewrite the backend.

Integrate cleanly.

Follow SOLID principles.

Write production-quality code.

Use type hints.

Use docstrings.

Avoid duplicate code.

Maintain backward compatibility.

========================================================================
OUTPUT FORMAT
========================================================================

Return:

1. Architecture analysis.

2. Content cache architecture.

3. OCR architecture.

4. Database migration.

5. Files modified.

6. Full implementation grouped by file path.

7. Testing instructions.

Do not provide partial snippets.

Provide complete production-ready implementations.
