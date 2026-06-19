"""
core/embedder.py — Embedding generation and similarity analysis for DocuWise.

Responsibilities:
  - Load the sentence-transformer model once (singleton pattern).
  - Generate L2-normalised embedding vectors from document text.
  - Persist embeddings as JSON in the database via update_document_embedding().
  - Compute pairwise cosine similarity across the corpus.
  - Detect duplicate and similar document pairs and write relationships.

This module does NOT perform:
  - Text extraction (see extractor.py)
  - Gemini API calls (see analyzer.py)
  - Any UI interaction
"""

import json
import logging
from typing import Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from config import (
    DEBUG_DUPLICATES,
    EMBEDDING_MODEL,
    MAX_TEXT_CHARS_FOR_LLM,
    NEAR_DUPLICATE_THRESHOLD,
    SIMILARITY_THRESHOLD,
)
from core.database import (
    _connect,
    get_all_documents,
    insert_relationship,
    update_document_embedding,
    update_document_status,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Singleton model loader
# ---------------------------------------------------------------------------

_model: Optional[SentenceTransformer] = None


def _get_model() -> SentenceTransformer:
    """
    Return the shared SentenceTransformer instance, loading it on first call.

    The model is downloaded automatically by sentence-transformers on the
    first run (~90 MB) and cached locally for all subsequent calls.
    Subsequent calls within the same process return the already-loaded
    instance with zero overhead.

    Returns:
        A ready-to-use SentenceTransformer model.

    Raises:
        RuntimeError: If the model cannot be loaded (e.g. no internet on
                      first run, or corrupted cache).
    """
    global _model
    if _model is None:
        logger.info("Loading embedding model '%s' (first call)...", EMBEDDING_MODEL)
        try:
            _model = SentenceTransformer(EMBEDDING_MODEL)
            logger.info("Embedding model loaded successfully.")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load embedding model '{EMBEDDING_MODEL}': {exc}"
            ) from exc
    return _model


# ---------------------------------------------------------------------------
# Core embedding functions
# ---------------------------------------------------------------------------

def generate_embedding(text: str) -> list[float]:
    """
    Generate a normalised embedding vector from plain text.

    The text is truncated to MAX_TEXT_CHARS_FOR_LLM characters before
    encoding to keep inference time predictable for large documents.
    The resulting vector is L2-normalised so that cosine similarity
    between any two embeddings equals their dot product — fast and
    numerically stable.

    Args:
        text: Plain-text string to embed. Must be non-empty.

    Returns:
        A Python list of floats representing the normalised embedding vector.
        The length is determined by the model (384 for all-MiniLM-L6-v2).

    Raises:
        ValueError: If *text* is empty or whitespace-only.
        RuntimeError: If the embedding model cannot be loaded.
    """
    if not text or not text.strip():
        raise ValueError("Cannot generate embedding for empty or whitespace-only text.")

    truncated = text[:MAX_TEXT_CHARS_FOR_LLM]

    model = _get_model()

    # encode() returns a numpy array; normalize_embeddings=True applies L2 norm.
    vector: np.ndarray = model.encode(
        truncated,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    return vector.tolist()


def cosine_similarity(
    embedding_a: list[float],
    embedding_b: list[float],
) -> float:
    """
    Compute cosine similarity between two embedding vectors.

    Because generate_embedding() always returns L2-normalised vectors,
    cosine similarity is equivalent to the dot product — making this
    operation a single vectorised multiply-and-sum with no division.

    For embeddings NOT produced by this module, the function falls back
    to the full cosine formula using numpy norms.

    Args:
        embedding_a: First embedding vector as a list of floats.
        embedding_b: Second embedding vector as a list of floats.

    Returns:
        Similarity score in range [-1.0, 1.0] where 1.0 = identical,
        0.0 = orthogonal, -1.0 = opposite. In practice, semantic
        similarity scores cluster in the range [0.0, 1.0].

    Raises:
        ValueError: If the two vectors have different lengths.
    """
    a = np.array(embedding_a, dtype=np.float32)
    b = np.array(embedding_b, dtype=np.float32)

    if a.shape != b.shape:
        raise ValueError(
            f"Embedding dimension mismatch: {a.shape} vs {b.shape}. "
            "Both vectors must have the same length."
        )

    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return float(np.dot(a, b) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# Pipeline integration — single document
# ---------------------------------------------------------------------------

def embed_document(file_path: str) -> bool:
    """
    Full embedding workflow for a single document.

    Steps:
      1. Load the document record from the database.
      2. Read the stored extracted_text field.
      3. Generate a normalised embedding vector.
      4. Serialise the vector to JSON and persist via update_document_embedding().
      5. Advance processing_status to 'embedded' on success or 'failed' on error.

    Called by the pipeline coordinator for every document with
    processing_status = 'extracted'. Safe to call multiple times —
    embedding writes are idempotent for the same file_path.

    Args:
        file_path: Absolute path to the document (primary DB key).

    Returns:
        True if embedding was generated and saved successfully, False otherwise.
    """
    logger.info("Embedding: '%s'", file_path)

    doc = _get_document(file_path)
    if doc is None:
        logger.error("Document not found in database: '%s'", file_path)
        return False

    extracted_text: Optional[str] = doc.get("extracted_text")
    if not extracted_text or not extracted_text.strip():
        msg = "No extracted text available. Run extractor first."
        logger.warning("Cannot embed '%s': %s", file_path, msg)
        update_document_status(file_path, "failed", error_message=msg)
        return False

    try:
        vector = generate_embedding(extracted_text)
        embedding_json = json.dumps(vector)
        update_document_embedding(file_path, embedding_json)
        logger.info(
            "Embedded '%s' | dim=%d | status→embedded",
            file_path, len(vector),
        )
        return True

    except (ValueError, RuntimeError) as exc:
        msg = f"Embedding generation failed: {exc}"
        logger.error("Embedding failed for '%s': %s", file_path, exc)
        update_document_status(file_path, "failed", error_message=msg)
        return False

    except Exception as exc:  # noqa: BLE001
        msg = f"Unexpected embedding error: {exc}"
        logger.error("Embedding failed for '%s': %s", file_path, exc, exc_info=True)
        update_document_status(file_path, "failed", error_message=msg)
        return False


# ---------------------------------------------------------------------------
# Similarity search
# ---------------------------------------------------------------------------

def find_similar_documents(
    document_id: int,
    top_k: int = 5,
) -> list[dict]:
    """
    Find the most similar documents to the given document by embedding similarity.

    Loads all embedded documents from the database, computes cosine similarity
    between the target document's embedding and every other embedded document,
    then returns the top-k results sorted by descending similarity.

    The target document itself is excluded from results.

    Args:
        document_id: Primary key of the document to search from.
        top_k:       Maximum number of similar documents to return.
                     Defaults to 5.

    Returns:
        List of dicts, sorted by similarity descending:
        [
            {
                "document_id": int,
                "filename":    str,
                "file_path":   str,
                "category":    str | None,
                "similarity":  float,
            },
            ...
        ]
        Returns an empty list if the target document has no embedding or
        if fewer than 2 embedded documents exist in the corpus.
    """
    all_docs = get_all_documents()
    embedded_docs = [
        d for d in all_docs
        if d.get("embedding_json") and d.get("id") is not None
    ]

    if len(embedded_docs) < 2:
        logger.debug("find_similar_documents: fewer than 2 embedded documents — skipping.")
        return []

    # Locate the target document.
    target = next((d for d in embedded_docs if d["id"] == document_id), None)
    if target is None:
        logger.warning(
            "find_similar_documents: document_id=%d has no embedding or does not exist.",
            document_id,
        )
        return []

    try:
        target_vector = json.loads(target["embedding_json"])
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error(
            "Could not parse embedding for document_id=%d: %s", document_id, exc
        )
        return []

    results: list[dict] = []

    for doc in embedded_docs:
        if doc["id"] == document_id:
            continue  # Skip self-comparison.

        try:
            other_vector = json.loads(doc["embedding_json"])
            score = cosine_similarity(target_vector, other_vector)
            results.append({
                "document_id": doc["id"],
                "filename":    doc.get("filename", ""),
                "file_path":   doc.get("file_path", ""),
                "category":    doc.get("category"),
                "similarity":  round(score, 6),
            })
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(
                "Skipping document_id=%d in similarity search: %s", doc["id"], exc
            )
            continue

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]


# ---------------------------------------------------------------------------
# Duplicate detection — full corpus pass
# ---------------------------------------------------------------------------

def detect_duplicates() -> dict:
    """
    Compute pairwise cosine similarity across all embedded documents and
    write duplicate / similar relationships to the database.

    Classification rules (from config.py):
      - similarity >= SIMILARITY_THRESHOLD      → relationship_type = 'duplicate'
      - similarity >= NEAR_DUPLICATE_THRESHOLD  → relationship_type = 'similar'
        (and similarity < SIMILARITY_THRESHOLD)
      - similarity < NEAR_DUPLICATE_THRESHOLD   → no relationship written

    Each pair (A, B) is processed only once (upper triangle of the similarity
    matrix) to avoid mirrored duplicate inserts. The database uses a
    UNIQUE(source, target, type) constraint as a second safety net.

    Returns:
        Summary dict:
        {
            "total_compared": int,     # number of unique pairs evaluated
            "duplicates_found": int,   # pairs classified as 'duplicate'
            "similar_found": int,      # pairs classified as 'similar'
            "errors": int,             # pairs skipped due to parse errors
        }
    """
    all_docs = get_all_documents()
    embedded_docs = [
        d for d in all_docs
        if d.get("embedding_json") and d.get("id") is not None
    ]

    n = len(embedded_docs)
    logger.info("Starting duplicate detection across %d embedded documents.", n)

    if n < 2:
        logger.info("Fewer than 2 embedded documents — skipping duplicate detection.")
        return {"total_compared": 0, "duplicates_found": 0, "similar_found": 0, "errors": 0}

    # ── Build embedding matrix ────────────────────────────────────────────────
    # Pre-loading all vectors avoids repeated JSON parsing during the O(n²) loop.
    vectors: list[Optional[np.ndarray]] = []
    for doc in embedded_docs:
        try:
            vectors.append(np.array(json.loads(doc["embedding_json"]), dtype=np.float32))
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning(
                "Skipping document_id=%d — invalid embedding JSON.", doc["id"]
            )
            vectors.append(None)

    # ── Pairwise comparison (upper triangle only) ─────────────────────────────
    counters = {"total_compared": 0, "duplicates_found": 0, "similar_found": 0, "errors": 0}

    # Collect ALL pair scores when debug mode enabled (for top-20 report).
    all_pairs: list[tuple[float, str, str]] = []  # (score, name_a, name_b)

    for i in range(n):
        if vectors[i] is None:
            continue

        for j in range(i + 1, n):  # j > i ensures each pair is seen exactly once
            if vectors[j] is None:
                continue

            counters["total_compared"] += 1

            try:
                score = float(np.dot(vectors[i], vectors[j]))  # both L2-normalised → dot = cosine
                # Clamp to [-1, 1] to guard against floating-point drift.
                score = max(-1.0, min(1.0, score))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Similarity computation failed for ids (%d, %d): %s",
                    embedded_docs[i]["id"], embedded_docs[j]["id"], exc,
                )
                counters["errors"] += 1
                continue

            name_a = embedded_docs[i].get("filename", str(embedded_docs[i]["id"]))
            name_b = embedded_docs[j].get("filename", str(embedded_docs[j]["id"]))

            if DEBUG_DUPLICATES:
                all_pairs.append((score, name_a, name_b))

            # Log every comparison that exceeds the lowest threshold.
            if score >= NEAR_DUPLICATE_THRESHOLD:
                logger.info(
                    "THRESHOLD HIT  %.4f | '%s'  ↔  '%s'",
                    score, name_a, name_b,
                )

            if score < NEAR_DUPLICATE_THRESHOLD:
                continue  # Not similar enough — skip writing a relationship.

            relationship_type = (
                "duplicate" if score >= SIMILARITY_THRESHOLD else "similar"
            )

            src_id  = embedded_docs[i]["id"]
            tgt_id  = embedded_docs[j]["id"]

            # Issue 5: skip if a relationship of this type already exists.
            if _relationship_exists(src_id, tgt_id, relationship_type):
                logger.debug(
                    "Skipping existing %s relationship: '%s' ↔ '%s'",
                    relationship_type, name_a, name_b,
                )
                continue

            try:
                insert_relationship(
                    source_document_id=src_id,
                    target_document_id=tgt_id,
                    relationship_type=relationship_type,
                    similarity_score=round(score, 6),
                    reason=(
                        f"Cosine similarity {score:.4f} >= "
                        f"{'SIMILARITY_THRESHOLD' if relationship_type == 'duplicate' else 'NEAR_DUPLICATE_THRESHOLD'} "
                        f"({SIMILARITY_THRESHOLD if relationship_type == 'duplicate' else NEAR_DUPLICATE_THRESHOLD})"
                    ),
                )

                if relationship_type == "duplicate":
                    counters["duplicates_found"] += 1
                    logger.info(
                        "DUPLICATE  '%s'  ↔  '%s'  |  score=%.4f",
                        name_a, name_b, score,
                    )
                else:
                    counters["similar_found"] += 1
                    logger.info(
                        "SIMILAR    '%s'  ↔  '%s'  |  score=%.4f",
                        name_a, name_b, score,
                    )

            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to insert relationship ('%s' ↔ '%s'): %s", name_a, name_b, exc
                )
                counters["errors"] += 1

    # ── DEBUG: Top-20 similarity pairs ────────────────────────────────────────
    if DEBUG_DUPLICATES and all_pairs:
        all_pairs.sort(key=lambda x: x[0], reverse=True)
        top = all_pairs[:20]
        logger.info("")
        logger.info("=" * 70)
        logger.info("DEBUG DUPLICATES — Top %d highest similarity pairs:", len(top))
        logger.info("=" * 70)
        for score, a, b in top:
            marker = "[DUPLICATE]" if score >= SIMILARITY_THRESHOLD else (
                     "[SIMILAR]  " if score >= NEAR_DUPLICATE_THRESHOLD else "           ")
            logger.info("  %.4f %s  '%s'  ↔  '%s'", score, marker, a, b)
        logger.info("=" * 70)
        logger.info("Thresholds: duplicate >= %.2f | similar >= %.2f",
                    SIMILARITY_THRESHOLD, NEAR_DUPLICATE_THRESHOLD)
        logger.info("=" * 70)
        logger.info("")

    logger.info(
        "Duplicate detection complete — compared=%d  duplicates=%d  similar=%d  errors=%d",
        counters["total_compared"],
        counters["duplicates_found"],
        counters["similar_found"],
        counters["errors"],
    )
    return counters


# ---------------------------------------------------------------------------
# Internal DB helper
# ---------------------------------------------------------------------------

def _get_document(file_path: str) -> Optional[dict]:
    """
    Retrieve a single document record from the database by file_path.

    Args:
        file_path: Absolute path used as the unique document key.

    Returns:
        Document dict or None if not found.
    """
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


def _relationship_exists(src_id: int, tgt_id: int, relationship_type: str) -> bool:
    """
    Check whether a relationship between two documents already exists in the DB.

    Checks both directions (src→tgt and tgt→src) to avoid creating
    mirrored duplicates across multiple scan runs.

    Args:
        src_id:            Source document primary key.
        tgt_id:            Target document primary key.
        relationship_type: e.g. 'duplicate' or 'similar'.

    Returns:
        True if the relationship already exists, False otherwise.
    """
    try:
        conn = _connect()
        with conn:
            row = conn.execute(
                """
                SELECT 1 FROM document_relationships
                 WHERE relationship_type = ?
                   AND (
                         (source_document_id = ? AND target_document_id = ?)
                      OR (source_document_id = ? AND target_document_id = ?)
                   )
                 LIMIT 1
                """,
                (relationship_type, src_id, tgt_id, tgt_id, src_id),
            ).fetchone()
        return row is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("_relationship_exists check failed (%d, %d): %s", src_id, tgt_id, exc)
        return False  # Assume it doesn't exist — let DB UNIQUE constraint catch actual dupes.
