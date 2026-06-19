"""
test_duplicate_debug.py — Read-only duplicate threshold diagnostic tool.

Loads all documents that have embedding_json from the database,
computes every pairwise cosine similarity, and prints the top-20
highest-scoring pairs WITHOUT writing anything to the database.

Usage:
    python test_duplicate_debug.py
"""

import json
import sys
import logging
import numpy as np

logging.basicConfig(level=logging.WARNING)  # Suppress INFO noise during model load

from core.database import _connect
from config import SIMILARITY_THRESHOLD, NEAR_DUPLICATE_THRESHOLD

# ─── Load embedded documents ───────────────────────────────────────────────────
conn = _connect()
rows = conn.execute("""
    SELECT id, filename, processing_status, embedding_json
    FROM documents
    WHERE embedding_json IS NOT NULL
    ORDER BY filename
""").fetchall()

docs = [dict(r) for r in rows]
n = len(docs)

print(f"\n{'='*70}")
print(f"  DocuWise — Duplicate Debug Report")
print(f"{'='*70}")
print(f"  Documents with embeddings: {n}")
print(f"  Thresholds:  duplicate >= {SIMILARITY_THRESHOLD}  |  similar >= {NEAR_DUPLICATE_THRESHOLD}")
print(f"{'='*70}\n")

if n < 2:
    print("  Not enough embedded documents for comparison (need at least 2).")
    sys.exit(0)

# ─── Parse embedding vectors ───────────────────────────────────────────────────
vectors: list = []
valid_docs: list = []
for doc in docs:
    try:
        v = np.array(json.loads(doc["embedding_json"]), dtype=np.float32)
        vectors.append(v)
        valid_docs.append(doc)
    except Exception as e:
        print(f"  [SKIP] Could not parse embedding for '{doc['filename']}': {e}")

n = len(valid_docs)
print(f"  Valid embeddings parsed: {n}\n")

# ─── Pairwise comparison ───────────────────────────────────────────────────────
pairs: list[tuple[float, str, str, str, str]] = []

for i in range(n):
    for j in range(i + 1, n):
        score = float(np.dot(vectors[i], vectors[j]))
        score = max(-1.0, min(1.0, score))
        label = (
            "DUPLICATE" if score >= SIMILARITY_THRESHOLD else
            "SIMILAR  " if score >= NEAR_DUPLICATE_THRESHOLD else
            "         "
        )
        pairs.append((
            score,
            label,
            valid_docs[i]["filename"],
            valid_docs[j]["filename"],
            valid_docs[i]["processing_status"],
        ))

pairs.sort(key=lambda x: x[0], reverse=True)
total_pairs = len(pairs)

# ─── Report ────────────────────────────────────────────────────────────────────
top_k = min(20, total_pairs)
print(f"  Total pairs computed: {total_pairs}")
print(f"  Showing top {top_k} by similarity:\n")
print(f"  {'Score':>6}  {'Label':10}  Pair")
print(f"  {'-'*6}  {'-'*10}  {'-'*50}")

for score, label, a, b, status in pairs[:top_k]:
    print(f"  {score:.4f}  {label}  '{a}'  <->  '{b}'")

above_similar   = sum(1 for p in pairs if p[0] >= NEAR_DUPLICATE_THRESHOLD)
above_duplicate = sum(1 for p in pairs if p[0] >= SIMILARITY_THRESHOLD)

print(f"\n  {'='*68}")
print(f"  Pairs above NEAR_DUPLICATE ({NEAR_DUPLICATE_THRESHOLD}): {above_similar}")
print(f"  Pairs above DUPLICATE      ({SIMILARITY_THRESHOLD}): {above_duplicate}")
print(f"  {'='*68}\n")

# ─── Status breakdown ─────────────────────────────────────────────────────────
statuses = {}
for doc in valid_docs:
    s = doc["processing_status"]
    statuses[s] = statuses.get(s, 0) + 1

print("  Status of embedded documents:")
for s, cnt in sorted(statuses.items()):
    print(f"    {s}: {cnt}")
print()
