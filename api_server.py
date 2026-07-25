"""
api_server.py — FastAPI bridge for DocuWise React + Tauri frontend.

This provides an HTTP API wrapping the existing SQLite database and
python processing pipeline. It requires zero changes to the backend business logic.
"""

import asyncio
import logging
import os
import queue
import re
import threading
import time
from typing import AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Import existing backend modules
from config import (
    DEFAULT_CATEGORIES,
    LLM_PROVIDER,
    OCR_ENABLED,
    OCR_ENGINE,
    OCR_LANGUAGE,
    OCR_VERSION,
    SUPPORTED_EXTENSIONS,
    CONTENT_CACHE_ENABLED,
)
from core.database import (
    _connect,
    get_all_documents,
    get_deletion_candidates,
    get_documents_by_status,
    get_extraction_metrics,
    get_missing_documents,
    get_relationships,
    get_total_documents,
    get_total_duplicates,
    get_total_embedded,
    get_total_failed,
    get_total_image_only,
    init_db,
)
from core.pipeline import run_full_scan

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_server")
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="DocuWise API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DB on startup
@app.on_event("startup")
def startup_event():
    init_db()

# ---------------------------------------------------------------------------
# Global SSE Queue for Scan Progress
# ---------------------------------------------------------------------------
# We use a custom logging handler to capture granular pipeline steps without
# modifying pipeline.py.
# Maps structured log event tokens (and legacy phrases) to the Phase 11
# live-scan stage names shown in the ScanOverlay. Order matters — the first
# matching token wins, so more specific events are listed before generic ones.
_STAGE_RULES = [
    ("OCR_STARTED", "OCR"),
    ("OCR_PAGE_COMPLETED", "OCR"),
    ("OCR_PAGE_SKIPPED", "OCR"),
    ("OCR_COMPLETED", "OCR"),
    ("OCR_FAILED", "OCR"),
    ("CONTENT_CACHE_HIT", "Cache Hit"),
    ("NVIDIA_SKIPPED_CACHE", "Cache Hit"),
    ("EMBEDDING_SKIPPED_CACHE", "Cache Hit"),
    ("CONTENT_CACHE_MISS", "Content Cache Lookup"),
    ("Detecting duplicates", "Duplicate Detection"),
    ("duplicate detection", "Duplicate Detection"),
    ("Analyzing", "Analyzing"),
    ("Analyzed", "Analyzing"),
    ("Embedding", "Embedding"),
    ("Embedded", "Embedding"),
    ("Scanning", "Scanning"),
    ("STAGE 1", "Scanning"),
    ("Extracted", "Native Extraction"),
    ("Extract", "Native Extraction"),
    ("Processing:", "Native Extraction"),
    ("Completed", "Saving"),
]


def _infer_stage(msg: str) -> str:
    """Map a log line to a live-scan stage name (Phase 11)."""
    for token, stage in _STAGE_RULES:
        if token in msg:
            return stage
    return "Processing"


class SSELogHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        msg = self.format(record)
        stage = _infer_stage(msg)

        # Parse a page number from structured OCR events (e.g. "page=3").
        page = None
        m = re.search(r"\bpage=(\d+)", msg)
        if m:
            try:
                page = int(m.group(1))
            except ValueError:
                page = None

        event = {"type": "log", "message": msg, "stage": stage}
        if page is not None:
            event["page"] = page

        try:
            self.q.put_nowait(event)
        except queue.Full:
            pass

scan_event_queue: queue.Queue = queue.Queue(maxsize=1000)
scan_in_progress = False
cancel_scan_flag = False

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ScanRequest(BaseModel):
    folder: str

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": "1.0"}

@app.get("/api/config")
def get_config():
    # Report whether the OCR backend actually loaded (PaddleOCR installed), so
    # the UI can distinguish "OCR configured" from "OCR usable".
    ocr_available = False
    if OCR_ENABLED:
        try:
            from core.ocr import get_ocr_engine
            ocr_available = get_ocr_engine().is_available()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"OCR availability check failed: {e}")
    return {
        "supported_extensions": SUPPORTED_EXTENSIONS,
        "categories": DEFAULT_CATEGORIES,
        "llm_provider": LLM_PROVIDER,
        "ocr_enabled": OCR_ENABLED,
        "ocr_engine": OCR_ENGINE,
        "ocr_version": OCR_VERSION,
        "ocr_language": OCR_LANGUAGE,
        "ocr_available": ocr_available,
        "content_cache_enabled": CONTENT_CACHE_ENABLED,
    }

def _like(folder: Optional[str]) -> Optional[str]:
    if not folder:
        return None
    return folder.rstrip("\\/") + "\\" + "%"

@app.get("/api/stats")
def get_stats(folder: Optional[str] = None):
    like = _like(folder)
    try:
        conn = _connect()
        if like:
            totals = conn.execute("""
                SELECT COUNT(*),
                    SUM(CASE WHEN processing_status='embedded'   THEN 1 ELSE 0 END),
                    SUM(CASE WHEN processing_status='image_only' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN deletion_candidate=1           THEN 1 ELSE 0 END),
                    SUM(CASE WHEN processing_status='missing'    THEN 1 ELSE 0 END),
                    SUM(CASE WHEN processing_status='failed'     THEN 1 ELSE 0 END)
                FROM documents WHERE file_path LIKE ?""", (like,)).fetchone()
            dups = conn.execute("""
                SELECT COUNT(*) FROM document_relationships dr
                JOIN documents d ON d.id=dr.source_document_id
                WHERE dr.relationship_type='duplicate' AND d.file_path LIKE ?
            """, (like,)).fetchone()
            cats = conn.execute("""
                SELECT category as name, COUNT(*) as count FROM documents
                WHERE category IS NOT NULL AND file_path LIKE ?
                GROUP BY category ORDER BY count DESC""", (like,)).fetchall()
            top = conn.execute("""
                SELECT filename, category, importance_score as importance FROM documents
                WHERE importance_score IS NOT NULL AND file_path LIKE ?
                ORDER BY importance_score DESC LIMIT 8""", (like,)).fetchall()
        else:
            totals = conn.execute("""
                SELECT COUNT(*),
                    SUM(CASE WHEN processing_status='embedded'   THEN 1 ELSE 0 END),
                    SUM(CASE WHEN processing_status='image_only' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN deletion_candidate=1           THEN 1 ELSE 0 END),
                    SUM(CASE WHEN processing_status='missing'    THEN 1 ELSE 0 END),
                    SUM(CASE WHEN processing_status='failed'     THEN 1 ELSE 0 END)
                FROM documents""").fetchone()
            dups = conn.execute("""
                SELECT COUNT(*) FROM document_relationships
                WHERE relationship_type='duplicate'""").fetchone()
            cats = conn.execute("""
                SELECT category as name, COUNT(*) as count FROM documents
                WHERE category IS NOT NULL
                GROUP BY category ORDER BY count DESC""").fetchall()
            top = conn.execute("""
                SELECT filename, category, importance_score as importance FROM documents
                WHERE importance_score IS NOT NULL
                ORDER BY importance_score DESC LIMIT 8""").fetchall()
        conn.close()

        # Extraction-method breakdown + OCR/cache metrics (Phase 10).
        extraction = get_extraction_metrics(folder)

        return {
            "total_documents": totals[0] or 0,
            "embedded": totals[1] or 0,
            "image_only": totals[2] or 0,
            "cleanup_candidates": totals[3] or 0,
            "missing": totals[4] or 0,
            "failed": totals[5] or 0,
            "duplicates": dups[0] or 0,
            "categories": [dict(c) for c in cats],
            "top_documents": [dict(t) for t in top],
            # Phase 10 — extraction & cache intelligence
            "native_documents": extraction["native_documents"],
            "hybrid_documents": extraction["hybrid_documents"],
            "ocr_only_documents": extraction["ocr_only_documents"],
            "image_only_documents": extraction["image_only_documents"],
            "ocr_cache_hits": extraction["ocr_cache_hits"],
            "content_cache_hits": extraction["content_cache_hits"],
            "api_calls_saved": extraction["api_calls_saved"],
            "embeddings_reused": extraction["embeddings_reused"],
            "avg_ocr_time_ms": extraction["avg_ocr_time_ms"],
        }
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/documents")
def get_documents(folder: Optional[str] = None, status: Optional[str] = None, category: Optional[str] = None, search: Optional[str] = None):
    try:
        conn = _connect()
        query = "SELECT * FROM documents WHERE 1=1"
        params = []
        
        if folder:
            query += " AND file_path LIKE ?"
            params.append(_like(folder))
        if status:
            query += " AND processing_status = ?"
            params.append(status)
        if category:
            query += " AND category = ?"
            params.append(category)
        if search:
            query += " AND (filename LIKE ? OR subject LIKE ? OR summary LIKE ?)"
            search_param = f"%{search}%"
            params.extend([search_param, search_param, search_param])
            
        query += " ORDER BY filename COLLATE NOCASE"
        
        rows = conn.execute(query, params).fetchall()
        conn.close()
        
        docs = []
        import json
        for r in rows:
            d = dict(r)
            if d.get("tags_json"):
                try:
                    d["tags"] = json.loads(d["tags_json"])
                except:
                    d["tags"] = []
            else:
                d["tags"] = []
            docs.append(d)
            
        return docs
    except Exception as e:
        logger.error(f"Failed to get documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/duplicates")
def get_duplicate_pairs(folder: Optional[str] = None):
    like = _like(folder)
    try:
        conn = _connect()
        if like:
            rows = conn.execute("""
                SELECT d1.filename as a_filename, d1.file_path as a_path, 
                       d2.filename as b_filename, d2.file_path as b_path,
                       d2.file_size_kb, dr.similarity_score, dr.relationship_type
                FROM document_relationships dr
                JOIN documents d1 ON d1.id=dr.source_document_id
                JOIN documents d2 ON d2.id=dr.target_document_id
                WHERE dr.relationship_type IN ('duplicate','similar')
                  AND d1.file_path LIKE ?
                ORDER BY dr.similarity_score DESC""", (like,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT d1.filename as a_filename, d1.file_path as a_path, 
                       d2.filename as b_filename, d2.file_path as b_path,
                       d2.file_size_kb, dr.similarity_score, dr.relationship_type
                FROM document_relationships dr
                JOIN documents d1 ON d1.id=dr.source_document_id
                JOIN documents d2 ON d2.id=dr.target_document_id
                WHERE dr.relationship_type IN ('duplicate','similar')
                ORDER BY dr.similarity_score DESC""").fetchall()
        conn.close()
        
        results = []
        for r in rows:
            results.append({
                "file_a": {"filename": r["a_filename"], "file_path": r["a_path"]},
                "file_b": {"filename": r["b_filename"], "file_path": r["b_path"], "file_size_kb": r["file_size_kb"]},
                "similarity_score": r["similarity_score"],
                "relationship_type": r["relationship_type"]
            })
        return results
    except Exception as e:
        logger.error(f"Failed to get duplicates: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/image-pdfs")
def get_image_pdfs(folder: Optional[str] = None):
    like = _like(folder)
    try:
        conn = _connect()
        if like:
            rows = conn.execute(
                "SELECT filename, file_path, file_size_kb FROM documents"
                " WHERE processing_status='image_only' AND file_path LIKE ?"
                " ORDER BY filename COLLATE NOCASE", (like,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT filename, file_path, file_size_kb FROM documents"
                " WHERE processing_status='image_only'"
                " ORDER BY filename COLLATE NOCASE"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get image PDFs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cleanup")
def get_cleanup(folder: Optional[str] = None):
    like = _like(folder)
    try:
        conn = _connect()
        
        # Get AI flagged cleanup candidates
        dels_query = """
            SELECT filename, file_path, deletion_reason as reason, importance_score
            FROM documents WHERE deletion_candidate=1
        """
        # Feature: exact duplicates (100% similarity) added to deletion candidates
        exact_dups_query = """
            SELECT d2.filename, d2.file_path, '100% Exact Duplicate' as reason, d2.importance_score
            FROM document_relationships dr
            JOIN documents d2 ON d2.id=dr.target_document_id
            JOIN documents d1 ON d1.id=dr.source_document_id
            WHERE dr.relationship_type='duplicate' AND dr.similarity_score > 0.99
        """
        
        miss_query = "SELECT filename, file_path FROM documents WHERE processing_status='missing'"
        
        params = []
        if like:
            dels_query += " AND file_path LIKE ?"
            exact_dups_query += " AND d1.file_path LIKE ?"
            miss_query += " AND file_path LIKE ?"
            params.append(like)
            
        dels = conn.execute(dels_query + " ORDER BY importance_score ASC", params).fetchall()
        exact_dups = conn.execute(exact_dups_query, params).fetchall()
        miss = conn.execute(miss_query + " ORDER BY filename COLLATE NOCASE", params).fetchall()
        conn.close()
        
        # Combine AI candidates and Exact Duplicates
        candidates = [dict(r) for r in dels]
        
        # Avoid double adding if exact duplicate is also flagged by AI
        existing_paths = {c["file_path"] for c in candidates}
        for d in exact_dups:
            if dict(d)["file_path"] not in existing_paths:
                candidates.append(dict(d))
                existing_paths.add(dict(d)["file_path"])
        
        return {
            "candidates": candidates,
            "missing": [dict(r) for r in miss]
        }
    except Exception as e:
        logger.error(f"Failed to get cleanup data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Scan Operations
# ---------------------------------------------------------------------------

@app.post("/api/scan/stop")
def stop_scan():
    global cancel_scan_flag
    if scan_in_progress:
        cancel_scan_flag = True
        return {"status": "stopping"}
    return {"status": "not_running"}

@app.post("/api/scan")
async def start_scan(req: ScanRequest):
    global scan_in_progress, cancel_scan_flag
    if scan_in_progress:
        raise HTTPException(status_code=400, detail="Scan already in progress")
    
    if not os.path.exists(req.folder):
        raise HTTPException(status_code=400, detail="Folder does not exist")
        
    scan_in_progress = True
    cancel_scan_flag = False
    
    # Clear queue
    while not scan_event_queue.empty():
        try: scan_event_queue.get_nowait()
        except queue.Empty: break
        
    def scan_thread():
        global scan_in_progress
        start_time = time.monotonic()
        
        # Attach log handler to capture granular events
        log_handler = SSELogHandler(scan_event_queue)
        logging.getLogger("core").addHandler(log_handler)
        
        def progress_cb(current, total, filename):
            elapsed = time.monotonic() - start_time
            # Infer stage based on cache hit
            stage = "Cache Hit" if "[cache hit" in filename.lower() else "Processing"
            try:
                scan_event_queue.put_nowait({
                    "type": "progress",
                    "current": current,
                    "total": total,
                    "filename": filename,
                    "stage": stage,
                    "elapsed_seconds": elapsed
                })
            except queue.Full:
                pass

        try:
            result = run_full_scan(
                req.folder, 
                progress_callback=progress_cb,
                is_cancelled=lambda: cancel_scan_flag
            )
            if cancel_scan_flag:
                scan_event_queue.put_nowait({"type": "error", "error": "Scan stopped by user"})
            else:
                scan_event_queue.put_nowait({"type": "complete", "result": result})
        except Exception as e:
            scan_event_queue.put_nowait({"type": "error", "error": str(e)})
        finally:
            logging.getLogger("core").removeHandler(log_handler)
            scan_in_progress = False

    t = threading.Thread(target=scan_thread, daemon=True)
    t.start()
    
    return {"status": "started", "folder": req.folder}

@app.get("/api/scan/progress")
async def scan_progress(request: Request):
    """SSE endpoint for streaming scan progress."""
    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            if await request.is_disconnected():
                break
                
            try:
                # Non-blocking check with small sleep to allow async context switch
                event = scan_event_queue.get_nowait()
                import json
                yield f"data: {json.dumps(event)}\n\n"
                if event["type"] in ("complete", "error"):
                    break
            except queue.Empty:
                await asyncio.sleep(0.1)
                
    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
