"""Test RapidOCR with batched recognition and number of threads."""
import time, sys, os
sys.path.insert(0, ".")
import fitz
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

pdf_path = r"D:\DocuWise_Test\Chemistry Lab Record.pdf"
doc = fitz.open(pdf_path)
page = doc[0]
pix = page.get_pixmap(dpi=100)
img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
arr = np.array(img)
doc.close()

# Test with different batch sizes and thread counts
for batch in [1, 6, 12]:
    for threads in [4, 8]:
        engine = RapidOCR(
            rec_batch_num=batch,
            det_use_cuda=False,
            intra_op_num_threads=threads,
        )
        
        t1 = time.time()
        result, elapse = engine(arr)
        ocr_time = time.time() - t1
        
        lines = len(result) if result else 0
        print(f"batch={batch:2d} threads={threads} | time={ocr_time:.2f}s | lines={lines} | det={elapse[0]:.1f}s cls={elapse[1]:.1f}s rec={elapse[2]:.1f}s")
