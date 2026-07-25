"""
tests/test_ocr_content_cache.py — Phase 14 test suite for DocuWise.

Covers the OCR + Content Cache integration end-to-end using an isolated temp
database and a fake, call-counting OCR engine (so tests never require the real
PaddleOCR model, a network connection, or the embedding model).

Scenarios (Phase 14):
    Native PDF · Scanned PDF · Mixed PDF · Image · Duplicate Image · Moved File
    Copied File · Cache Hit · Cache Miss · Corrupt PDF · Large PDF · Image Only

Assertions (Phase 14):
    No duplicate OCR · No duplicate NVIDIA calls · No duplicate embeddings
    Correct cache restoration · Correct database updates

Run:
    venv/Scripts/python -m unittest tests.test_ocr_content_cache -v
    venv/Scripts/python tests/test_ocr_content_cache.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

# Make the project root importable when run as a file.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz  # PyMuPDF
from PIL import Image, ImageDraw

import config
from core import database as db
from core import ocr as ocr_mod
from core import content_cache
from core.ocr import BaseOCREngine, OCRResult


# ---------------------------------------------------------------------------
# Fake OCR engine (call-counting, no real model)
# ---------------------------------------------------------------------------

class FakeOCREngine(BaseOCREngine):
    name = "fake"
    version = "fake-1"

    def __init__(self, text: str = "OCR RECOVERED invoice tax total amount due", available: bool = True):
        self._text = text
        self._available = available
        self.calls = 0

    def is_available(self) -> bool:
        return self._available

    def recognize(self, image) -> OCRResult:
        self.calls += 1
        if not self._available:
            return OCRResult(success=False, error_message="unavailable")
        return OCRResult(text=self._text, confidence=0.9, line_count=3, success=True)


# ---------------------------------------------------------------------------
# PDF / image builders
# ---------------------------------------------------------------------------

def _make_text_pdf(path: str, pages_text: list) -> None:
    """Create a PDF; each item in pages_text is that page's text ('' = blank)."""
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=12)
    doc.save(path)
    doc.close()


def _make_png(path: str) -> None:
    img = Image.new("RGB", (300, 120), color="white")
    ImageDraw.Draw(img).text((10, 40), "placeholder", fill="black")
    img.save(path)


def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


# ---------------------------------------------------------------------------
# Base test case — isolated temp DB + injected OCR engine
# ---------------------------------------------------------------------------

class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="docuwise_test_")
        self._orig_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tmp, "test.db")
        config.DB_PATH = db.DB_PATH
        db.init_db()

        # Inject a fake OCR engine as the singleton.
        self.ocr = FakeOCREngine()
        ocr_mod._engine_instance = self.ocr

    def tearDown(self):
        ocr_mod.reset_ocr_engine()
        db.DB_PATH = self._orig_db_path
        config.DB_PATH = self._orig_db_path
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def _insert(self, path: str) -> None:
        p = os.path.abspath(path)
        db.insert_document(p, os.path.basename(p), os.path.splitext(p)[1].lower(), 1.0)

    def _process(self, path: str):
        from core.extractor import process_document
        return process_document(os.path.abspath(path))


# ---------------------------------------------------------------------------
# Extraction method tests
# ---------------------------------------------------------------------------

class TestExtractionMethods(_Base):

    def test_native_pdf(self):
        p = os.path.join(self.tmp, "native.pdf")
        _make_text_pdf(p, ["This is a fully native PDF page with plenty of real text content."])
        self._insert(p)
        r = self._process(p)
        self.assertTrue(r.success)
        self.assertFalse(r.image_only)
        self.assertEqual(r.extraction_method, "native")
        self.assertEqual(self.ocr.calls, 0, "native PDF must never invoke OCR")

    def test_scanned_pdf_ocr_only(self):
        p = os.path.join(self.tmp, "scanned.pdf")
        _make_text_pdf(p, [""])  # blank page → no native text
        self._insert(p)
        r = self._process(p)
        self.assertTrue(r.success)
        self.assertEqual(r.extraction_method, "ocr_only")
        self.assertEqual(self.ocr.calls, 1)
        self.assertIn("OCR RECOVERED", r.text)

    def test_mixed_pdf_hybrid(self):
        p = os.path.join(self.tmp, "mixed.pdf")
        _make_text_pdf(p, ["Page one has genuine native text that exceeds the threshold.", ""])
        self._insert(p)
        r = self._process(p)
        self.assertTrue(r.success)
        self.assertEqual(r.extraction_method, "hybrid")
        self.assertEqual(self.ocr.calls, 1, "only the text-poor page should be OCR'd")
        self.assertEqual(r.ocr_pages_processed, 1)
        self.assertEqual(r.ocr_pages_skipped, 1)

    def test_image_ocr_only(self):
        p = os.path.join(self.tmp, "photo.png")
        _make_png(p)
        self._insert(p)
        r = self._process(p)
        self.assertTrue(r.success)
        self.assertEqual(r.extraction_method, "ocr_only")
        self.assertEqual(self.ocr.calls, 1)

    def test_image_only_when_ocr_unavailable(self):
        self.ocr._available = False  # simulate PaddleOCR not installed
        p = os.path.join(self.tmp, "scanned2.pdf")
        _make_text_pdf(p, [""])
        self._insert(p)
        r = self._process(p)
        self.assertTrue(r.success)          # not a failure — graceful degrade
        self.assertTrue(r.image_only)
        self.assertEqual(r.extraction_method, "image_only")
        row = db.get_document(os.path.abspath(p))
        self.assertEqual(row["processing_status"], "image_only")

    def test_large_pdf_respects_page_cap(self):
        from config import OCR_MAX_PDF_PAGES
        n = OCR_MAX_PDF_PAGES + 5
        p = os.path.join(self.tmp, "large.pdf")
        _make_text_pdf(p, [""] * n)  # all blank → all candidates for OCR
        self._insert(p)
        r = self._process(p)
        self.assertTrue(r.success)
        self.assertEqual(r.ocr_pages_processed, OCR_MAX_PDF_PAGES)
        self.assertEqual(self.ocr.calls, OCR_MAX_PDF_PAGES,
                         "OCR must stop at OCR_MAX_PDF_PAGES")

    def test_corrupt_pdf_fails_gracefully(self):
        p = os.path.join(self.tmp, "corrupt.pdf")
        with open(p, "wb") as fh:
            fh.write(b"%PDF-1.4 this is not a valid pdf body at all")
        self._insert(p)
        r = self._process(p)
        self.assertFalse(r.success)
        row = db.get_document(os.path.abspath(p))
        self.assertEqual(row["processing_status"], "failed")


# ---------------------------------------------------------------------------
# Content cache: no-duplicate-work tests
# ---------------------------------------------------------------------------

class TestContentCache(_Base):

    def test_copied_file_reuses_ocr_text(self):
        """A byte-identical copy must NOT re-run OCR (text hit)."""
        a = os.path.join(self.tmp, "a.png")
        _make_png(a)
        self._insert(a)
        self._process(a)
        self.assertEqual(self.ocr.calls, 1)

        b = os.path.join(self.tmp, "b.png")   # identical content copy
        shutil.copy(a, b)
        self._insert(b)
        r = self._process(b)
        self.assertTrue(r.success)
        self.assertEqual(self.ocr.calls, 1, "duplicate content must reuse cached OCR text")
        self.assertEqual(r.ocr_cached, 1)

    def test_cache_miss_then_hit_via_pipeline(self):
        """Full pipeline: first file is a miss; identical copy is a complete hit
        that skips NVIDIA analysis AND embedding."""
        import core.pipeline as pipeline

        calls = {"analyze": 0, "embed": 0}

        def fake_analyze(file_path, user_rules=None):
            calls["analyze"] += 1
            db.update_document_analysis(
                file_path, "a summary", "Finance", "tax", json.dumps(["tax"]),
                7, 0, None, 0, None, "nvidia",
            )
            return SimpleNamespace(success=True, error_message=None)

        def fake_embed(file_path):
            calls["embed"] += 1
            db.update_document_embedding(file_path, json.dumps([0.1, 0.2, 0.3]))
            return True

        orig_analyze, orig_embed = pipeline.analyze_document, pipeline.embed_document
        pipeline.analyze_document = fake_analyze
        pipeline.embed_document = fake_embed
        try:
            a = os.path.join(self.tmp, "doc.txt")
            _write(a, "Finance invoice tax content. " * 30)
            self._insert(a)
            res1 = pipeline.process_pending_documents()

            # Byte-identical copy — should be a complete content-cache hit.
            b = os.path.join(self.tmp, "doc_copy.txt")
            shutil.copy(a, b)
            self._insert(b)
            res2 = pipeline.process_pending_documents()
        finally:
            pipeline.analyze_document = orig_analyze
            pipeline.embed_document = orig_embed

        # First pass: one analyze, one embed, no cache hit.
        self.assertEqual(res1["processed"], 1)
        self.assertEqual(res1["content_cache_hits"], 0)

        # Second pass: NO new analyze, NO new embed — served from cache.
        self.assertEqual(calls["analyze"], 1, "NVIDIA must be called exactly once")
        self.assertEqual(calls["embed"], 1, "embedding must be generated exactly once")
        self.assertEqual(res2["content_cache_hits"], 1)
        self.assertEqual(res2["nvidia_skipped"], 1)
        self.assertEqual(res2["embeddings_reused"], 1)

        # Correct cache restoration into the DB.
        row_b = db.get_document(os.path.abspath(b))
        self.assertEqual(row_b["processing_status"], "embedded")
        self.assertEqual(row_b["analysis_source"], "cached")
        self.assertEqual(row_b["summary"], "a summary")
        self.assertTrue(row_b["embedding_json"])

    def test_moved_file_reuses_cache(self):
        """A file that moves to a new path (same bytes, new documents row) must
        reuse the cached analysis rather than re-analysing."""
        import core.pipeline as pipeline

        calls = {"analyze": 0, "embed": 0}

        def fake_analyze(file_path, user_rules=None):
            calls["analyze"] += 1
            db.update_document_analysis(
                file_path, "s", "Work", "topic", json.dumps(["x"]),
                6, 0, None, 0, None, "nvidia",
            )
            return SimpleNamespace(success=True, error_message=None)

        def fake_embed(file_path):
            calls["embed"] += 1
            db.update_document_embedding(file_path, json.dumps([0.4, 0.5]))
            return True

        orig_a, orig_e = pipeline.analyze_document, pipeline.embed_document
        pipeline.analyze_document, pipeline.embed_document = fake_analyze, fake_embed
        try:
            src = os.path.join(self.tmp, "orig.txt")
            _write(src, "Work project report content here. " * 20)
            self._insert(src)
            pipeline.process_pending_documents()

            # "Move": same bytes at a new path (old row left as-is / would be
            # flagged missing by a real scan; here we just index the new path).
            dst = os.path.join(self.tmp, "sub_moved.txt")
            shutil.move(src, dst)
            self._insert(dst)
            res = pipeline.process_pending_documents()
        finally:
            pipeline.analyze_document, pipeline.embed_document = orig_a, orig_e

        self.assertEqual(calls["analyze"], 1, "moved file must not re-analyse")
        self.assertEqual(calls["embed"], 1, "moved file must not re-embed")
        self.assertEqual(res["content_cache_hits"], 1)


# ---------------------------------------------------------------------------
# Database migration sanity
# ---------------------------------------------------------------------------

class TestSchema(_Base):

    def test_content_cache_table_and_columns(self):
        conn = db._connect()
        cc_cols = [r[1] for r in conn.execute("PRAGMA table_info(content_cache)").fetchall()]
        for col in ("md5_hash", "native_text", "ocr_text", "final_text",
                    "extraction_method", "embedding_json", "summary", "ocr_confidence"):
            self.assertIn(col, cc_cols)

        doc_cols = [r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()]
        for col in ("extraction_method", "ocr_engine", "ocr_version", "ocr_confidence",
                    "ocr_pages_processed", "ocr_pages_skipped", "ocr_processing_time_ms",
                    "ocr_cached"):
            self.assertIn(col, doc_cols)
        conn.close()

    def test_extraction_metrics_shape(self):
        m = db.get_extraction_metrics()
        for key in ("native_documents", "hybrid_documents", "ocr_only_documents",
                    "image_only_documents", "ocr_cache_hits", "content_cache_hits",
                    "api_calls_saved", "embeddings_reused", "avg_ocr_time_ms"):
            self.assertIn(key, m)


if __name__ == "__main__":
    unittest.main(verbosity=2)
