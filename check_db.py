import sqlite3

conn = sqlite3.connect("storage/docuwise.db")

cursor = conn.execute("""
SELECT
    filename,
    category,
    subject,
    importance_score,
    processing_status
FROM documents
""")

for row in cursor.fetchall():
    print(row)

conn.close()