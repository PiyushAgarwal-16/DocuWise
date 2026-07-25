import sqlite3

def reset_image_only_docs():
    conn = sqlite3.connect("storage/docuwise.db")
    with conn:
        cursor = conn.execute("SELECT count(*) FROM documents WHERE processing_status = 'image_only' AND ocr_engine IS NULL")
        count = cursor.fetchone()[0]
        
        if count > 0:
            conn.execute("UPDATE documents SET processing_status = 'pending', extraction_method = NULL WHERE processing_status = 'image_only' AND ocr_engine IS NULL")
            print(f"Reset {count} documents to 'pending' for OCR retry.")
        else:
            print("No documents found that need an OCR retry.")

if __name__ == "__main__":
    reset_image_only_docs()
