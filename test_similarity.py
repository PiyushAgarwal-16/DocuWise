from core.embedder import generate_embedding, cosine_similarity

a = """
Java ArrayList implementation with insertion,
deletion and traversal examples.
"""

b = """
ArrayList operations in Java including insert,
delete and traversal.
"""

c = """
Chocolate cake recipe with cocoa powder,
butter and sugar.
"""

e1 = generate_embedding(a)
e2 = generate_embedding(b)
e3 = generate_embedding(c)

print("A-B:", cosine_similarity(e1, e2))
print("A-C:", cosine_similarity(e1, e3))