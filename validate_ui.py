"""Validate the new UI data paths against the live database."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')

import sqlite3
conn = sqlite3.connect('storage/docuwise.db')
conn.row_factory = sqlite3.Row

test_folder = r"D:\DocuWise_Test"
like = test_folder.rstrip("\\/") + "\\" + "%"

print("=" * 60)
print("DOCUWISE UI DATA VISIBILITY VALIDATION")
print("=" * 60)

# 1. Dashboard stat cards
print("\n1. DASHBOARD — Stat Cards")
row = conn.execute("""
    SELECT COUNT(*) as total,
        SUM(CASE WHEN processing_status='embedded'   THEN 1 ELSE 0 END) as embedded,
        SUM(CASE WHEN processing_status='image_only' THEN 1 ELSE 0 END) as image_only,
        SUM(CASE WHEN deletion_candidate=1           THEN 1 ELSE 0 END) as cleanup,
        SUM(CASE WHEN processing_status='missing'    THEN 1 ELSE 0 END) as missing
    FROM documents WHERE file_path LIKE ?""", (like,)).fetchone()
print(f"   Total={row['total']} Embedded={row['embedded']} Image={row['image_only']} Cleanup={row['cleanup']} Missing={row['missing']}")

dup = conn.execute("""
    SELECT COUNT(*) as c FROM document_relationships dr
    JOIN documents d ON d.id=dr.source_document_id
    WHERE dr.relationship_type='duplicate' AND d.file_path LIKE ?""", (like,)).fetchone()
print(f"   Duplicates={dup['c']}")

# 2. Documents view
print("\n2. DOCUMENTS VIEW — Row count")
docs = conn.execute(
    "SELECT COUNT(*) as c FROM documents WHERE file_path LIKE ? ORDER BY filename COLLATE NOCASE",
    (like,)).fetchone()
print(f"   Documents matching folder: {docs['c']}")

# 3. Duplicates view
print("\n3. DUPLICATES VIEW — Pair count")
dups = conn.execute("""
    SELECT COUNT(*) as c FROM document_relationships dr
    JOIN documents d1 ON d1.id=dr.source_document_id
    JOIN documents d2 ON d2.id=dr.target_document_id
    WHERE dr.relationship_type IN ('duplicate','similar')
      AND d1.file_path LIKE ?""", (like,)).fetchall()
print(f"   Duplicate/similar pairs: {dups[0]['c']}")

# 4. Image PDFs view
print("\n4. IMAGE PDFs VIEW — Count")
imgs = conn.execute(
    "SELECT COUNT(*) as c FROM documents WHERE processing_status='image_only' AND file_path LIKE ?",
    (like,)).fetchone()
print(f"   Image-only PDFs: {imgs['c']}")

# 5. Cleanup view
print("\n5. CLEANUP VIEW — Counts")
dels = conn.execute(
    "SELECT COUNT(*) as c FROM documents WHERE deletion_candidate=1 AND file_path LIKE ?",
    (like,)).fetchone()
miss = conn.execute(
    "SELECT COUNT(*) as c FROM documents WHERE processing_status='missing' AND file_path LIKE ?",
    (like,)).fetchone()
print(f"   Deletion candidates: {dels['c']}")
print(f"   Missing files: {miss['c']}")

# 6. Category distribution
print("\n6. CATEGORY DISTRIBUTION")
cats = conn.execute("""
    SELECT category, COUNT(*) as c FROM documents
    WHERE category IS NOT NULL AND file_path LIKE ?
    GROUP BY category ORDER BY c DESC""", (like,)).fetchall()
for r in cats:
    print(f"   {r['category']:20s}: {r['c']}")

# 7. Stats vs data agreement
print("\n7. CONSISTENCY CHECK")
total_db = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
total_filtered = conn.execute("SELECT COUNT(*) FROM documents WHERE file_path LIKE ?", (like,)).fetchone()[0]
print(f"   Total in DB: {total_db}")
print(f"   Total matching folder '{test_folder}': {total_filtered}")

# Verify all expected data is non-zero
checks = [
    ("Dashboard total docs", row['total']),
    ("Documents view rows", docs['c']),
]
all_pass = True
for name, val in checks:
    status = "✓ PASS" if val and val > 0 else "✗ FAIL"
    if val == 0 or val is None:
        all_pass = False
    print(f"   {status}: {name} = {val}")

print("\n" + "=" * 60)
print(f"RESULT: {'ALL CHECKS PASSED ✓' if all_pass else 'SOME CHECKS FAILED ✗'}")
print("=" * 60)

# 8. Also test global (no folder filter) path
print("\n8. GLOBAL VIEW (no folder filter)")
global_row = conn.execute("""
    SELECT COUNT(*) as total,
        SUM(CASE WHEN processing_status='embedded'   THEN 1 ELSE 0 END) as embedded,
        SUM(CASE WHEN processing_status='image_only' THEN 1 ELSE 0 END) as image_only
    FROM documents""").fetchone()
print(f"   Total={global_row['total']} Embedded={global_row['embedded']} Image={global_row['image_only']}")

conn.close()
