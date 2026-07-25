"""
core/search.py — Hybrid Semantic Search engine for DocuWise.

Implements the multi-signal ranking algorithm combining dense vector embeddings
with keyword and knowledge-profile signals. Uses an in-memory NumPy matrix
for vector similarity.
"""

import json
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from config import (
    SEARCH_BOOST_EXACT_MATCH,
    SEARCH_BOOST_IMPORTANCE,
    SEARCH_DEFAULT_LIMIT,
    SEARCH_MIN_SCORE,
    SEARCH_WEIGHTS,
)
from core.database import _connect
from core.embedder import generate_embedding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent Detection (Deterministic NLP)
# ---------------------------------------------------------------------------

INTENT_DOC_TYPES = {
    "notes": ["lecture notes", "notes"],
    "lecture": ["lecture notes"],
    "slides": ["presentation"],
    "presentation": ["presentation"],
    "resume": ["resume", "cv"],
    "cv": ["resume", "cv"],
    "paper": ["research paper", "paper"],
    "research": ["research paper"],
    "cheat sheet": ["cheat sheet", "reference"],
    "textbook": ["textbook"],
    "assignment": ["assignment", "homework"],
    "exam": ["exam", "test"],
    "report": ["report"],
    "tutorial": ["tutorial", "guide"],
}

INTENT_NOISE_WORDS = {
    "show", "me", "find", "get", "list", "give",
    "search", "for", "look", "all", "the", "my",
    "about", "related", "to", "on", "with",
}

def process_query(raw_query: str) -> Tuple[str, Optional[str]]:
    """
    Normalize query, strip noise words, and detect doc_type intents.
    Returns (clean_query, doc_type_filter).
    """
    # 1. Normalize
    q = raw_query.lower()
    q = re.sub(r"[^\w\s]", "", q).strip()
    tokens = q.split()

    # 2. Intent Detection
    doc_type_filter = None
    for token in tokens:
        if token in INTENT_DOC_TYPES:
            doc_type_filter = INTENT_DOC_TYPES[token][0]
            break  # Just take the first matched doc_type for now

    # 3. Strip Noise Words & Intents
    clean_tokens = []
    for token in tokens:
        if token in INTENT_NOISE_WORDS or token in INTENT_DOC_TYPES:
            continue
        clean_tokens.append(token)
    
    clean_query = " ".join(clean_tokens)
    # Fallback to raw normalized query if stripping left it empty
    if not clean_query:
        clean_query = q

    return clean_query, doc_type_filter

# ---------------------------------------------------------------------------
# Concept Expansion
# ---------------------------------------------------------------------------

def expand_concepts(query: str) -> List[str]:
    """
    Search concepts_json for the query and discover related concepts by
    co-occurrence frequency across documents.
    """
    if not query:
        return []
    
    conn = _connect()
    with conn:
        # Find all documents whose concepts mention the query
        like_q = f"%{query}%"
        rows = conn.execute(
            "SELECT concepts_json FROM knowledge_profiles WHERE concepts_json LIKE ?",
            (like_q,)
        ).fetchall()
        
    freq = {}
    for r in rows:
        try:
            concepts = json.loads(r["concepts_json"])
            for c in concepts:
                c_lower = str(c).strip().lower()
                if query not in c_lower:  # Exclude the query itself
                    freq[c_lower] = freq.get(c_lower, 0) + 1
        except Exception:
            continue

    # Return top 5 co-occurring concepts
    sorted_concepts = sorted(freq.keys(), key=lambda k: freq[k], reverse=True)
    return sorted_concepts[:5]

# ---------------------------------------------------------------------------
# Vector Backend
# ---------------------------------------------------------------------------

class NumpyBackend:
    """In-memory vector store using NumPy for fast cosine similarity."""

    def __init__(self):
        self.doc_ids: List[int] = []
        self.matrix: Optional[np.ndarray] = None
        self.is_built = False

    def build_index(self):
        """Fetch all embeddings from the database and build the matrix."""
        logger.info("Building NumpyBackend search index...")
        conn = _connect()
        with conn:
            rows = conn.execute(
                "SELECT id, embedding_json FROM documents WHERE embedding_json IS NOT NULL AND processing_status IN ('embedded', 'analyzed', 'completed')"
            ).fetchall()

        ids = []
        vecs = []
        for r in rows:
            try:
                vec = json.loads(r["embedding_json"])
                ids.append(r["id"])
                vecs.append(vec)
            except Exception:
                continue

        self.doc_ids = ids
        if vecs:
            self.matrix = np.array(vecs, dtype=np.float32)
        else:
            self.matrix = np.empty((0, 384), dtype=np.float32)
        
        self.is_built = True
        logger.info(f"Search index built with {len(self.doc_ids)} documents.")

    def add_to_index(self, doc_id: int, embedding: List[float]):
        """Dynamically add a new document's embedding to the index."""
        if not self.is_built:
            self.build_index()
            return
            
        if doc_id in self.doc_ids:
            # Update existing
            idx = self.doc_ids.index(doc_id)
            self.matrix[idx] = np.array(embedding, dtype=np.float32)
        else:
            # Append new
            self.doc_ids.append(doc_id)
            vec = np.array(embedding, dtype=np.float32).reshape(1, -1)
            if self.matrix is not None and self.matrix.size > 0:
                self.matrix = np.vstack([self.matrix, vec])
            else:
                self.matrix = vec

    def search(self, query_vector: List[float]) -> Dict[int, float]:
        """Compute cosine similarity. Returns dict of {doc_id: score}."""
        if not self.is_built:
            self.build_index()
            
        if self.matrix is None or self.matrix.shape[0] == 0:
            return {}
            
        q_vec = np.array(query_vector, dtype=np.float32)
        # Cosine similarity is dot product because vectors are L2-normalized
        scores = np.dot(self.matrix, q_vec)
        
        return {doc_id: float(score) for doc_id, score in zip(self.doc_ids, scores)}

# Global backend instance
vector_backend = NumpyBackend()

# ---------------------------------------------------------------------------
# Signal Fusion
# ---------------------------------------------------------------------------

def _score_string_match(query_tokens: set[str], target: str) -> float:
    if not target:
        return 0.0
    target_lower = target.lower()
    matches = sum(1 for t in query_tokens if t in target_lower)
    return min(1.0, matches / max(1, len(query_tokens)))

def _score_list_match(query_tokens: set[str], target_list: List[str]) -> float:
    if not target_list:
        return 0.0
    target_text = " ".join(str(i).lower() for i in target_list)
    matches = sum(1 for t in query_tokens if t in target_text)
    return min(1.0, matches / max(1, len(query_tokens)))

# ---------------------------------------------------------------------------
# Search Engine
# ---------------------------------------------------------------------------

def perform_search(
    query: str,
    limit: int = SEARCH_DEFAULT_LIMIT,
    category_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Execute a hybrid search using the 7-signal ranking algorithm.
    """
    if not query.strip():
        return []

    # 1. NLP Pipeline
    clean_query, doc_type_filter = process_query(query)
    expanded_concepts = expand_concepts(clean_query)
    
    query_tokens = set(clean_query.split())
    expanded_tokens = set(" ".join(expanded_concepts).split())
    all_tokens = query_tokens.union(expanded_tokens)
    
    if not query_tokens:
        return []

    # 2. Vector Search
    query_embedding = generate_embedding(clean_query)
    vector_scores = vector_backend.search(query_embedding)
    
    # 3. Fetch Candidate Data
    conn = _connect()
    candidates = []
    with conn:
        sql = """
            SELECT d.id, d.filename, d.file_path, d.category, d.subject, 
                   d.summary, d.tags_json, d.importance_score, d.word_count,
                   k.concepts_json, k.entities_json, k.domains_json, k.doc_type
            FROM documents d
            LEFT JOIN knowledge_profiles k ON k.document_id = d.id
            WHERE d.processing_status IN ('embedded', 'analyzed', 'completed')
        """
        params = []
        if category_filter:
            sql += " AND d.category = ?"
            params.append(category_filter)
        if doc_type_filter:
            sql += " AND k.doc_type = ?"
            params.append(doc_type_filter)
            
        rows = conn.execute(sql, params).fetchall()
        for r in rows:
            doc = dict(r)
            doc["vector_score"] = vector_scores.get(doc["id"], 0.0)
            candidates.append(doc)

    # 4. Multi-Signal Fusion
    results = []
    for doc in candidates:
        try:
            tags = json.loads(doc.get("tags_json") or "[]")
            concepts = json.loads(doc.get("concepts_json") or "[]")
            entities = json.loads(doc.get("entities_json") or "[]")
            domains = json.loads(doc.get("domains_json") or "[]")
        except Exception:
            tags, concepts, entities, domains = [], [], [], []

        # Signal 1: Embedding
        s_emb = doc["vector_score"]
        
        # Signal 2: Concepts (boosted if matches primary query, else expanded)
        s_con = _score_list_match(all_tokens, concepts)
        
        # Signal 3: Entities (parse name from dict)
        ent_names = [e.get("name", "") for e in entities if isinstance(e, dict)]
        s_ent = _score_list_match(query_tokens, ent_names)
        
        # Signal 4: Summary / Subject
        s_sum = _score_string_match(query_tokens, doc.get("summary", ""))
        s_sum = max(s_sum, _score_string_match(query_tokens, doc.get("subject", "")))
        
        # Signal 5: Tags
        s_tag = _score_list_match(query_tokens, tags)
        
        # Signal 6: Domains
        s_dom = _score_list_match(query_tokens, domains)
        
        # Signal 7: Filename
        s_file = _score_string_match(query_tokens, doc.get("filename", ""))

        # Weighted Sum
        base_score = (
            s_emb * SEARCH_WEIGHTS["embedding"] +
            s_con * SEARCH_WEIGHTS["concepts"] +
            s_ent * SEARCH_WEIGHTS["entities"] +
            s_sum * SEARCH_WEIGHTS["summary"] +
            s_tag * SEARCH_WEIGHTS["tags"] +
            s_dom * SEARCH_WEIGHTS["domains"] +
            s_file * SEARCH_WEIGHTS["filename"]
        )

        # Boosts
        # Importance boost: max 0.5 for importance 10
        imp = int(doc.get("importance_score") or 5)
        imp_boost = 1.0 + (imp * SEARCH_BOOST_IMPORTANCE)
        
        # Exact match boost on subject or filename
        exact_boost = 1.0
        if clean_query in str(doc.get("subject", "")).lower() or clean_query in str(doc.get("filename", "")).lower():
            exact_boost = SEARCH_BOOST_EXACT_MATCH

        final_score = base_score * imp_boost * exact_boost

        if final_score >= SEARCH_MIN_SCORE:
            doc["search_score"] = final_score
            doc["signals"] = {
                "embedding": s_emb,
                "concepts": s_con,
                "entities": s_ent,
                "summary": s_sum,
                "tags": s_tag,
                "domains": s_dom,
                "filename": s_file,
            }
            results.append(doc)

    # 5. Sort & Return
    results.sort(key=lambda x: x["search_score"], reverse=True)
    return results[:limit]

def find_related_documents(doc_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Find related documents using vector similarity of the document's embedding.
    """
    conn = _connect()
    with conn:
        doc = conn.execute("SELECT embedding_json FROM documents WHERE id = ?", (doc_id,)).fetchone()
        
    if not doc or not doc["embedding_json"]:
        return []
        
    try:
        embedding = json.loads(doc["embedding_json"])
    except Exception:
        return []
        
    # Get vector scores
    vector_scores = vector_backend.search(embedding)
    
    # Sort and get top K (excluding the document itself)
    sorted_docs = sorted(
        [(k, v) for k, v in vector_scores.items() if k != doc_id],
        key=lambda x: x[1], 
        reverse=True
    )
    
    top_k = sorted_docs[:limit]
    if not top_k:
        return []
        
    candidate_ids = [k[0] for k in top_k]
    
    # Fetch document metadata for these IDs
    results = []
    with conn:
        placeholders = ",".join("?" * len(candidate_ids))
        sql = f"""
            SELECT d.id, d.filename, d.file_path, d.category, d.subject, 
                   d.summary, k.concepts_json, k.doc_type
            FROM documents d
            LEFT JOIN knowledge_profiles k ON k.document_id = d.id
            WHERE d.id IN ({placeholders})
        """
        rows = conn.execute(sql, candidate_ids).fetchall()
        for r in rows:
            doc_dict = dict(r)
            # Find score
            score = next((v for k, v in top_k if k == doc_dict["id"]), 0.0)
            doc_dict["similarity_score"] = float(score)
            results.append(doc_dict)
            
    # Sort again because SQL IN doesn't preserve order
    results.sort(key=lambda x: x["similarity_score"], reverse=True)
    return results
