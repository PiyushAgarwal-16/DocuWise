import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

# Test 1: provider initialisation
from core.llm_provider import get_provider, HeuristicProvider, NvidiaProvider, _extract_json
from core.analyzer import DocumentAnalysis, analyze_text, validate_model

p = get_provider()
print(f"Provider: {type(p).__name__}")
print(f"validate_model(): {validate_model()}")
print()

# Test 2: improved JSON extraction
cases = [
    ('Raw JSON',          '{"summary":"test","importance_score":7}'),
    ('Fenced JSON',       '```json\n{"summary":"test","importance_score":7}\n```\nSome prose after.'),
    ('JSON + prose',      'Sure! Here is the analysis:\n{"summary":"test","importance_score":7}\nHope this helps!'),
    ('Nested braces',     '{"summary":"test (v2)","tags":["a","b"],"importance_score":5}'),
]
print("JSON extraction tests:")
for label, raw in cases:
    result = _extract_json(raw)
    ok = result is not None and isinstance(result, dict)
    print(f"  [{('OK' if ok else 'FAIL')}] {label}: {result}")
print()

# Test 3: end-to-end analyze_text (goes to NVIDIA)
print("analyze_text() smoke test:")
r = analyze_text("Java ArrayList implementation with insertion, deletion and traversal.")
print(f"  success={r.success}  category={r.category}  importance={r.importance_score}  confidence={r.confidence_score}")
print(f"  summary={r.summary[:80]}")
print(f"  error={r.error_message}")
