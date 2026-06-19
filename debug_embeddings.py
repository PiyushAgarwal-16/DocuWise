"""
Diagnostic script — audits detect_duplicates() step by step.
Run with:  venv\Scripts\python debug_embeddings.py
"""
import json
import sqlite3
import numpy as np

DB = "storage/docuwise.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# ── 1. Raw DB inspection ──────────────────────────────────────────────────────
print("=" * 70)
print("STEP 1: Raw DB — embedded documents")
print("=" * 70)
rows = conn.execute(
    "SELECT id, filename, processing_status, embedding_json FROM documents"
    " WHERE processing_status = 'embedded'"
).fetchall()

print(f"  Embedded doc count: {len(rows)}\n")
vectors = []
for r in rows:
    ej = r["embedding_json"]
    if ej is None:
        print(f"  id={r['id']:3d}  *** embedding_json IS NULL ***  {r['filename']}")
        vectors.append(None)
        continue
    try:
        v = json.loads(ej)
        norm = float(np.linalg.norm(v))
        print(f"  id={r['id']:3d}  dim={len(v)}  norm={norm:.6f}  {r['filename'][:60]}")
        vectors.append((r["id"], r["filename"], np.array(v, dtype=np.float32)))
    except Exception as e:
        print(f"  id={r['id']:3d}  JSON PARSE ERROR: {e}  raw[:60]={str(ej)[:60]}")
        vectors.append(None)

conn.close()

# ── 2. Pairwise similarity — full matrix with diagnostics ─────────────────────
print()
print("=" * 70)
print("STEP 2: Pairwise cosine similarity (all valid pairs)")
print("=" * 70)

valid = [v for v in vectors if v is not None]
n = len(valid)
print(f"  Valid embedded vectors: {n}")
print(f"  Expected pairs (n*(n-1)/2): {n*(n-1)//2}\n")

scores = []
for i in range(n):
    id_a, name_a, vec_a = valid[i]
    for j in range(i + 1, n):
        id_b, name_b, vec_b = valid[j]
        # dot product of L2-normalised vectors = cosine similarity
        dot = float(np.dot(vec_a, vec_b))
        norm_a = float(np.linalg.norm(vec_a))
        norm_b = float(np.linalg.norm(vec_b))
        cosine = dot / (norm_a * norm_b) if norm_a > 0 and norm_b > 0 else 0.0
        scores.append((cosine, name_a, name_b))

scores.sort(reverse=True)

print(f"  Top 20 highest similarity scores:\n")
print(f"  {'Score':>8}  {'File A':<40}  {'File B'}")
print(f"  {'-'*8}  {'-'*40}  {'-'*40}")
for score, a, b in scores[:20]:
    print(f"  {score:8.6f}  {a[:40]:<40}  {b[:40]}")

# ── 3. Threshold check ────────────────────────────────────────────────────────
SIMILARITY_THRESHOLD = 0.88
NEAR_DUPLICATE_THRESHOLD = 0.75

print()
print("=" * 70)
print(f"STEP 3: Threshold analysis")
print(f"  SIMILARITY_THRESHOLD     = {SIMILARITY_THRESHOLD}")
print(f"  NEAR_DUPLICATE_THRESHOLD = {NEAR_DUPLICATE_THRESHOLD}")
print("=" * 70)

would_be_duplicate = [(s, a, b) for s, a, b in scores if s >= SIMILARITY_THRESHOLD]
would_be_similar   = [(s, a, b) for s, a, b in scores if NEAR_DUPLICATE_THRESHOLD <= s < SIMILARITY_THRESHOLD]

print(f"\n  Pairs that SHOULD be 'duplicate' (score >= {SIMILARITY_THRESHOLD}): {len(would_be_duplicate)}")
for s, a, b in would_be_duplicate:
    print(f"    {s:.6f}  {a}  ↔  {b}")

print(f"\n  Pairs that SHOULD be 'similar'   (score >= {NEAR_DUPLICATE_THRESHOLD}): {len(would_be_similar)}")
for s, a, b in would_be_similar:
    print(f"    {s:.6f}  {a}  ↔  {b}")

# ── 4. Simulate detect_duplicates() logic exactly ─────────────────────────────
print()
print("=" * 70)
print("STEP 4: Simulating detect_duplicates() get_all_documents() path")
print("=" * 70)
from core.database import get_all_documents

all_docs = get_all_documents()
print(f"  get_all_documents() returned {len(all_docs)} total documents")

embedded_docs = [
    d for d in all_docs
    if d.get("embedding_json") and d.get("id") is not None
]
print(f"  After filter (embedding_json not None, id not None): {len(embedded_docs)} docs")

# Check what embedding_json looks like through this path
print()
for d in embedded_docs[:3]:
    ej = d.get("embedding_json")
    ej_type = type(ej).__name__
    ej_preview = str(ej)[:80] if ej else "None"
    print(f"  id={d['id']}  embedding_json type={ej_type}  preview={ej_preview}")

print()
print("  Building numpy vectors via json.loads()...")
built = []
for d in embedded_docs:
    try:
        v = np.array(json.loads(d["embedding_json"]), dtype=np.float32)
        built.append((d["id"], d.get("filename","?"), v))
    except Exception as e:
        print(f"  FAILED for id={d['id']}: {e}")

print(f"  Successfully built {len(built)} vectors from get_all_documents() path")

# ── 5. Verdict ────────────────────────────────────────────────────────────────
print()
print("=" * 70)
print("VERDICT")
print("=" * 70)
if not would_be_duplicate and not would_be_similar:
    print("  ⚠  No pairs exceed NEAR_DUPLICATE_THRESHOLD.")
    print("  The corpus itself may be too diverse, OR embeddings are not")
    print("  generated from the same text that was compared in test_similarity.py.")
    print(f"  Highest score in corpus: {scores[0][0]:.6f} ({scores[0][1]} ↔ {scores[0][2]})")
else:
    if len(built) == n:
        print("  ✓  Embeddings load correctly via get_all_documents().")
    print(f"  ✓  {len(would_be_duplicate)} duplicate pair(s) and {len(would_be_similar)} similar pair(s) detected.")
    print("  → Root cause is NOT in the embedding/similarity math.")
    print("  → Check _relationship_exists() or insert_relationship() for silent failures.")
