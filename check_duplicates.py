import sqlite3

conn = sqlite3.connect("storage/docuwise.db")

cursor = conn.execute("""
SELECT
    source_document_id,
    target_document_id,
    relationship_type,
    similarity_score
FROM document_relationships
""")

for row in cursor.fetchall():
    print(row)

conn.close()