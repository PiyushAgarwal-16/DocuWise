from core.database import _connect

conn = _connect()

# Check failed docs that have analysis data
rows = conn.execute("""
    SELECT filename, processing_status, category, subject, embedding_json IS NOT NULL as has_embedding
    FROM documents
    WHERE processing_status = 'failed' AND category IS NOT NULL
    LIMIT 15
""").fetchall()

print("=== FAILED docs WITH analysis data (status corruption candidates) ===")
for r in rows:
    print(dict(r))

print()

# All status counts
rows2 = conn.execute("""
    SELECT processing_status, COUNT(*) as cnt FROM documents GROUP BY processing_status
""").fetchall()
print("=== Status distribution ===")
for r in rows2:
    print(dict(r))

print()

# How many have embeddings
rows3 = conn.execute("""
    SELECT COUNT(*) as cnt FROM documents WHERE embedding_json IS NOT NULL
""").fetchone()
print(f"Documents with embeddings: {dict(rows3)}")

# Check the known duplicates
rows4 = conn.execute("""
    SELECT filename, processing_status, embedding_json IS NOT NULL as has_embedding
    FROM documents
    WHERE filename LIKE '%Circular%' OR filename LIKE '%CV Latest%'
""").fetchall()
print()
print("=== Known duplicate candidates ===")
for r in rows4:
    print(dict(r))
