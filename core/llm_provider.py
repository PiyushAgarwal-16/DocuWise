"""
core/llm_provider.py — LLM provider abstraction layer for DocuWise.

Providers:  NvidiaProvider (primary) | GeminiProvider (secondary) | HeuristicProvider (fallback)
Features:   Smart text sampling · Robust JSON extraction · Category enforcement
            Per-scan budget tracking · Metrics · user_rules hook for future rules engine
"""

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from config import (
    API_CALL_DELAY_SECONDS,
    DEFAULT_CATEGORIES,
    ENABLE_FALLBACK_ANALYSIS,
    ENABLE_LLM_ANALYSIS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_TEMPERATURE,
    LLM_PROVIDER,
    LLM_TEMPERATURE,
    MAX_LLM_REQUESTS_PER_SCAN,
    MAX_TAGS_PER_DOCUMENT,
    MAX_TEXT_CHARS_FOR_LLM,
    NVIDIA_API_KEY,
    NVIDIA_BASE_URL,
    NVIDIA_MODEL,
    NVIDIA_REQUEST_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass (Part 12 — analysis_source field)
# ---------------------------------------------------------------------------

@dataclass
class DocumentAnalysis:
    """Structured result from a single document analysis call."""
    summary: str = ""
    category: str = "Miscellaneous"
    subject: str = ""
    tags: list[str] = field(default_factory=list)
    importance_score: int = 5
    deletion_candidate: bool = False
    deletion_reason: str = ""
    confidence_score: float = 0.5
    analysis_source: str = ""        # "nvidia" | "gemini" | "fallback" | "cached"
    success: bool = False
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Part 13 — Observability metrics
# ---------------------------------------------------------------------------

_metrics: dict = {
    "documents_analyzed": 0,
    "documents_cached": 0,
    "documents_fallback": 0,
    "api_calls_made": 0,
    "api_calls_saved": 0,
    "rate_limit_waits": 0,
    "total_analysis_time": 0.0,
    "analysis_count": 0,
}

# Part 5 — Per-scan budget tracker
_scan_budget: dict = {"used": 0, "exhausted": False}


def get_metrics() -> dict:
    """Return a copy of the current observability metrics."""
    m = dict(_metrics)
    m["average_analysis_time"] = (
        round(m["total_analysis_time"] / m["analysis_count"], 2)
        if m["analysis_count"] > 0 else 0.0
    )
    return m


def reset_scan_budget() -> None:
    """Reset the per-scan LLM request budget. Call at the start of each scan."""
    _scan_budget["used"] = 0
    _scan_budget["exhausted"] = False
    logger.info("Scan LLM budget reset. Limit: %d requests.", MAX_LLM_REQUESTS_PER_SCAN)


def is_budget_exhausted() -> bool:
    """True if MAX_LLM_REQUESTS_PER_SCAN has been reached this scan."""
    return _scan_budget["exhausted"]


def _consume_budget() -> bool:
    """
    Attempt to consume one unit of the scan budget.
    Returns True if budget available, False if exhausted.
    """
    if _scan_budget["exhausted"]:
        return False
    _scan_budget["used"] += 1
    if _scan_budget["used"] >= MAX_LLM_REQUESTS_PER_SCAN:
        _scan_budget["exhausted"] = True
        logger.warning(
            "LLM request budget exhausted (%d/%d). "
            "Remaining files will retain 'pending' status.",
            _scan_budget["used"], MAX_LLM_REQUESTS_PER_SCAN,
        )
    return True


# ---------------------------------------------------------------------------
# Part 4 — Smart content reduction (max 3500 chars)
# ---------------------------------------------------------------------------

def prepare_text_for_llm(text: str) -> str:
    """
    Intelligently sample up to 3500 chars from a document.

    Strategy: first 1500 + middle 1000 + last 1000 characters.
    Reduces token usage by ~90% while preserving the document's
    beginning, core content, and conclusion.
    """
    if len(text) <= 3500:
        return text
    first  = text[:1500]
    mid_s  = (len(text) - 1000) // 2
    middle = text[mid_s : mid_s + 1000]
    last   = text[-1000:]
    return (
        f"{first}\n\n[... middle excerpt ...]\n\n{middle}"
        f"\n\n[... final excerpt ...]\n\n{last}"
    )


# ---------------------------------------------------------------------------
# Part 7 — Robust JSON extraction
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> Optional[dict]:
    """
    Extract the first valid JSON object from any LLM response format.

    Handles:
      1. Pure JSON
      2. Markdown fenced JSON  (```json ... ```)
      3. JSON followed by explanation prose
      4. Prose followed by JSON
      5. Multiple code fences (takes the first valid one)
    """
    # 1. Fast path: entire string is valid JSON
    try:
        obj = json.loads(raw.strip())
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 2. Markdown code fence (all variants)
    for fence_match in re.finditer(r"```(?:json)?\s*([\s\S]+?)\s*```", raw, re.IGNORECASE):
        try:
            obj = json.loads(fence_match.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    # 3 & 4. First balanced { ... } block anywhere in the text
    start = raw.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(raw[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(raw[start : i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break

    return None


# ---------------------------------------------------------------------------
# Part 8 — Category enforcement
# ---------------------------------------------------------------------------

# Maps common non-standard values to valid categories.
_CATEGORY_ALIASES: dict[str, str] = {
    "data structures":   "Technical",
    "algorithms":        "Technical",
    "programming":       "Technical",
    "software":          "Technical",
    "computer science":  "Technical",
    "networking":        "Technical",
    "mathematics":       "Academic",
    "science":           "Academic",
    "physics":           "Academic",
    "chemistry":         "Academic",
    "biology":           "Academic",
    "history":           "Academic",
    "education":         "Academic",
    "accounting":        "Finance",
    "banking":           "Finance",
    "investment":        "Finance",
    "insurance":         "Finance",
    "employment":        "Work",
    "business":          "Work",
    "management":        "Work",
    "contract":          "Legal",
    "agreement":         "Legal",
    "policy":            "Legal",
    "health":            "Personal",
    "medical":           "Personal",
    "diary":             "Personal",
}


def _enforce_category(raw: str, subject: str) -> tuple[str, str]:
    """
    Enforce that category is one of DEFAULT_CATEGORIES.

    If the model returned an unrecognised value (e.g. "Data Structures"):
      - map it to the nearest valid category via _CATEGORY_ALIASES
      - promote the raw value to subject if subject is blank/generic

    Returns:
        (category, subject) — both validated / corrected.
    """
    if raw in DEFAULT_CATEGORIES:
        return raw, subject

    normalised = raw.strip().lower()

    # Direct alias lookup
    if normalised in _CATEGORY_ALIASES:
        mapped = _CATEGORY_ALIASES[normalised]
        new_subject = subject if subject and subject.lower() != "general" else raw
        logger.debug("Category '%s' mapped to '%s'. Subject set to '%s'.", raw, mapped, new_subject)
        return mapped, new_subject

    # Partial match against alias keys
    for alias_key, alias_cat in _CATEGORY_ALIASES.items():
        if alias_key in normalised or normalised in alias_key:
            new_subject = subject if subject and subject.lower() != "general" else raw
            logger.debug("Category '%s' partial-matched to '%s'.", raw, alias_cat)
            return alias_cat, new_subject

    # Nothing matched — default to Miscellaneous, preserve raw as subject
    new_subject = subject if subject and subject.lower() != "general" else raw
    logger.debug("Unknown category '%s' — defaulting to Miscellaneous.", raw)
    return "Miscellaneous", new_subject


# ---------------------------------------------------------------------------
# Part 10 — High-quality shared prompt
# ---------------------------------------------------------------------------

_CATEGORY_LIST = "\n".join(f"  - {c}" for c in DEFAULT_CATEGORIES)

_SYSTEM_PROMPT = f"""You are a document intelligence assistant for a file management system.
Analyze the provided document text and return ONLY a JSON object — no markdown, no explanation.

JSON SCHEMA (all fields required):
{{
  "summary": "<maximum 2 sentences describing the document content>",
  "category": "<exactly one from the allowed list below>",
  "subject": "<specific topic in 3-8 words>",
  "tags": ["<keyword1>", "<keyword2>", "<keyword3>"],
  "importance_score": <integer 1-10>,
  "deletion_candidate": <true or false>,
  "deletion_reason": "<one short sentence if true, else empty string>",
  "confidence_score": <float 0.0-1.0>
}}

ALLOWED CATEGORIES ONLY:
{_CATEGORY_LIST}

RULES:
- Output valid JSON ONLY. No markdown. No prose before or after.
- summary: max 2 sentences, plain English, no bullet points.
- subject: 3–8 words, lowercase preferred.
- tags: 2–{MAX_TAGS_PER_DOCUMENT} lowercase keyword strings.
- importance_score: integer 1 (junk) to 10 (critical), based on content value.
- deletion_candidate: true only for clearly redundant, empty, or junk content.
- confidence_score: your certainty about this analysis, 0.0 to 1.0.
- category MUST be one of the allowed values — use Miscellaneous if unsure.
"""


def _build_prompt(text: str, user_rules: Optional[str] = None) -> str:
    """Assemble the full prompt, optionally injecting active user rules."""
    rules_section = ""
    if user_rules:
        rules_section = (
            f"\nACTIVE USER RULES (apply these when scoring importance and flags):\n"
            f"{user_rules}\n"
        )
    return (
        f"{_SYSTEM_PROMPT}{rules_section}\n"
        f"DOCUMENT TEXT:\n{'=' * 60}\n{text}\n{'=' * 60}\n\n"
        f"Return the JSON now:"
    )


# ---------------------------------------------------------------------------
# Shared validation & dataclass construction
# ---------------------------------------------------------------------------

def _validate_and_build(data: dict, source: str) -> DocumentAnalysis:
    """Validate all LLM JSON fields and return a clean DocumentAnalysis."""
    summary = str(data.get("summary", "")).strip() or "No summary available."

    raw_category = str(data.get("category", "")).strip()
    raw_subject  = str(data.get("subject",  "")).strip() or "General"
    category, subject = _enforce_category(raw_category, raw_subject)

    raw_tags = data.get("tags", [])
    tags = (
        [str(t).strip().lower() for t in raw_tags if str(t).strip()][:MAX_TAGS_PER_DOCUMENT]
        if isinstance(raw_tags, list) else []
    )

    try:
        importance_score = max(1, min(10, int(data.get("importance_score", 5))))
    except (TypeError, ValueError):
        importance_score = 5

    raw_del = data.get("deletion_candidate", False)
    deletion_candidate = (
        raw_del if isinstance(raw_del, bool)
        else str(raw_del).strip().lower() in ("true", "1", "yes")
    )
    deletion_reason = str(data.get("deletion_reason", "")).strip()
    if not deletion_candidate:
        deletion_reason = ""

    try:
        confidence_score = max(0.0, min(1.0, float(data.get("confidence_score", 0.5))))
    except (TypeError, ValueError):
        confidence_score = 0.5

    return DocumentAnalysis(
        summary=summary, category=category, subject=subject, tags=tags,
        importance_score=importance_score, deletion_candidate=deletion_candidate,
        deletion_reason=deletion_reason, confidence_score=confidence_score,
        analysis_source=source, success=True,
    )


# ---------------------------------------------------------------------------
# Abstract base (Part 1 + Part 11 — user_rules parameter)
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """Abstract base for all LLM analysis providers."""

    @abstractmethod
    def analyze(
        self,
        text: str,
        user_rules: Optional[str] = None,   # Part 11 — reserved for future rules engine
    ) -> DocumentAnalysis:
        """Analyze document text and return structured metadata."""


# ---------------------------------------------------------------------------
# NVIDIA NIM Provider — primary (Parts 1, 5, 6, 7, 10)
# ---------------------------------------------------------------------------

class NvidiaProvider(LLMProvider):
    """Document analysis via NVIDIA NIM (OpenAI-compatible REST API)."""

    def __init__(self) -> None:
        if not NVIDIA_API_KEY:
            raise RuntimeError(
                "NVIDIA_API_KEY is not set in config.py. "
                "Obtain a key from https://build.nvidia.com/"
            )
        from openai import OpenAI
        self._client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY)
        logger.info("NvidiaProvider ready — model='%s'", NVIDIA_MODEL)

    def analyze(self, text: str, user_rules: Optional[str] = None) -> DocumentAnalysis:
        # Part 5 — budget gate
        if not _consume_budget():
            return DocumentAnalysis(
                success=False,
                error_message="LLM request budget exhausted for this scan.",
                analysis_source="nvidia",
            )

        sampled = prepare_text_for_llm(text)
        prompt  = _build_prompt(sampled, user_rules)

        from core.rate_limiter import check_and_wait, record_request  # Part 6

        retry_delays = [30.0, 60.0]
        t_start = time.time()

        for attempt in range(1, 3):
            try:
                slept = check_and_wait("nvidia")          # Part 6 — rate limit
                if slept > NVIDIA_REQUEST_DELAY_SECONDS:
                    _metrics["rate_limit_waits"] += 1

                logger.debug("NVIDIA API call (attempt %d).", attempt)
                response = self._client.chat.completions.create(
                    model=NVIDIA_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=LLM_TEMPERATURE,
                    max_tokens=1024,
                )
                record_request("nvidia")
                _metrics["api_calls_made"] += 1

                raw_text = response.choices[0].message.content or ""
                parsed = _extract_json(raw_text)

                if parsed is None:
                    logger.warning(
                        "Attempt %d: no JSON in NVIDIA response. Raw[:200]: %s",
                        attempt, raw_text[:200],
                    )
                    if attempt < 2:
                        time.sleep(API_CALL_DELAY_SECONDS)
                        continue
                    return DocumentAnalysis(
                        success=False, analysis_source="nvidia",
                        error_message="NVIDIA returned unparseable JSON after 2 attempts.",
                    )

                result = _validate_and_build(parsed, "nvidia")
                elapsed = time.time() - t_start
                _metrics["total_analysis_time"] += elapsed
                _metrics["analysis_count"] += 1
                _metrics["documents_analyzed"] += 1
                logger.debug(
                    "NVIDIA OK — category='%s' importance=%d confidence=%.2f (%.1fs)",
                    result.category, result.importance_score, result.confidence_score, elapsed,
                )
                return result

            except Exception as exc:  # noqa: BLE001
                exc_str = str(exc).lower()
                is_rate = any(k in exc_str for k in ("429", "resource_exhausted", "quota", "rate limit", "too many"))
                wait = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                if is_rate:
                    logger.warning("NVIDIA rate limit (attempt %d). Sleeping %.0fs.", attempt, wait)
                else:
                    logger.error("NVIDIA API error (attempt %d): %s", attempt, exc)
                if attempt < 2:
                    time.sleep(wait)
                    continue
                return DocumentAnalysis(
                    success=False, analysis_source="nvidia",
                    error_message=f"NVIDIA API error: {exc}",
                )

        return DocumentAnalysis(success=False, analysis_source="nvidia",
                                error_message="NVIDIA analysis failed after all attempts.")


# ---------------------------------------------------------------------------
# Gemini Provider — secondary
# ---------------------------------------------------------------------------

class GeminiProvider(LLMProvider):
    """Document analysis via Google Gemini (google-generativeai SDK)."""

    def __init__(self) -> None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set in config.py.")
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        self._model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            generation_config=genai.GenerationConfig(
                temperature=GEMINI_TEMPERATURE,
                response_mime_type="application/json",
            ),
        )
        logger.info("GeminiProvider ready — model='%s'", GEMINI_MODEL)

    def analyze(self, text: str, user_rules: Optional[str] = None) -> DocumentAnalysis:
        if not _consume_budget():
            return DocumentAnalysis(success=False, error_message="LLM budget exhausted.",
                                    analysis_source="gemini")
        sampled = prepare_text_for_llm(text)
        prompt  = _build_prompt(sampled, user_rules)
        retry_delays = [30.0, 60.0]
        for attempt in range(1, 3):
            try:
                time.sleep(API_CALL_DELAY_SECONDS)
                response = self._model.generate_content(prompt)
                _metrics["api_calls_made"] += 1
                parsed = _extract_json(response.text or "")
                if parsed is None:
                    if attempt < 2:
                        continue
                    return DocumentAnalysis(success=False, analysis_source="gemini",
                                            error_message="Gemini returned unparseable JSON.")
                result = _validate_and_build(parsed, "gemini")
                _metrics["documents_analyzed"] += 1
                return result
            except Exception as exc:  # noqa: BLE001
                if attempt < 2:
                    time.sleep(retry_delays[0])
                    continue
                return DocumentAnalysis(success=False, analysis_source="gemini",
                                        error_message=f"Gemini error: {exc}")
        return DocumentAnalysis(success=False, analysis_source="gemini",
                                error_message="Gemini failed after all attempts.")


# ---------------------------------------------------------------------------
# Part 9 — Heuristic fallback (keyword-based, never fails)
# ---------------------------------------------------------------------------

class HeuristicProvider(LLMProvider):
    """
    Offline fallback analyzer using keyword matching.
    Never raises an exception. confidence_score always 0.50–0.75.
    """

    _KEYWORDS: dict[str, list[str]] = {
        "Academic":  [
            "jee", "neet", "physics", "chemistry", "mathematics", "exam", "syllabus",
            "cbse", "ncert", "board", "semester", "lecture", "study", "notes", "class",
            "university", "college", "homework", "assignment", "textbook",
        ],
        "Technical": [
            "java", "python", "javascript", "c++", "database", "algorithm", "coding",
            "linked list", "arraylist", "sql", "api", "software", "programming",
            "function", "class", "method", "array", "stack", "queue", "tree", "graph",
            "server", "network", "machine learning", "neural", "model", "github",
        ],
        "Finance":   [
            "invoice", "receipt", "tax", "salary", "budget", "expense", "income",
            "payment", "bank", "transaction", "financial", "account", "credit", "debit",
            "rupee", "dollar", "gst", "balance",
        ],
        "Legal":     [
            "contract", "agreement", "legal", "law", "court", "clause", "terms",
            "conditions", "policy", "rights", "liability", "attorney", "jurisdiction",
        ],
        "Personal":  [
            "resume", "cv", "curriculum vitae", "certificate", "bonafide", "admit card",
            "personal", "health", "medical", "family", "diary", "journal", "letter",
        ],
        "Work":      [
            "report", "meeting", "project", "deadline", "client", "proposal",
            "presentation", "manager", "employee", "office", "business", "professional",
        ],
    }

    _STOPWORDS: set[str] = {
        "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
        "is", "are", "was", "were", "with", "that", "this", "it", "be", "by",
        "from", "as", "into", "not", "but", "if", "do", "did", "will", "can",
        "may", "its", "they", "have", "has", "had", "their", "so",
    }

    def analyze(self, text: str, user_rules: Optional[str] = None) -> DocumentAnalysis:
        words = text.lower().split()
        word_count = len(words)
        text_lower = text.lower()

        # Category scoring
        scores: dict[str, int] = {cat: 0 for cat in self._KEYWORDS}
        for cat, kws in self._KEYWORDS.items():
            for kw in kws:
                scores[cat] += text_lower.count(kw)

        best_cat = max(scores, key=scores.get)  # type: ignore[arg-type]
        category = best_cat if scores[best_cat] > 0 else "Miscellaneous"

        # Confidence based on keyword match strength
        top_score = scores[best_cat]
        confidence = min(0.75, 0.50 + top_score * 0.02)

        # Summary from first 2 sentences
        sentences = re.split(r"[.!?]+", text.strip())
        parts = [s.strip() for s in sentences[:2] if s.strip()]
        summary = ". ".join(parts) + "." if parts else "No summary available."
        if len(summary) > 250:
            summary = summary[:247] + "..."

        # Importance from word count
        importance_score = (
            3 if word_count < 100 else
            5 if word_count < 500 else
            7 if word_count < 2_000 else 8
        )

        # Tags: top frequent non-stopword words
        freq: dict[str, int] = {}
        for w in words:
            clean = re.sub(r"[^a-z0-9]", "", w)
            if len(clean) > 3 and clean not in self._STOPWORDS:
                freq[clean] = freq.get(clean, 0) + 1
        tags = sorted(freq, key=freq.get, reverse=True)[:MAX_TAGS_PER_DOCUMENT]  # type: ignore

        is_junk = word_count < 50
        _metrics["documents_fallback"] += 1
        return DocumentAnalysis(
            summary=summary,
            category=category,
            subject=f"{category} document",
            tags=tags,
            importance_score=importance_score,
            deletion_candidate=is_junk,
            deletion_reason="Very short document — possibly empty or minimal content." if is_junk else "",
            confidence_score=round(confidence, 2),
            analysis_source="fallback",
            success=True,
        )


# ---------------------------------------------------------------------------
# Provider factory (singleton)
# ---------------------------------------------------------------------------

_provider_instance: Optional[LLMProvider] = None


def get_provider() -> LLMProvider:
    """
    Return the globally shared LLM provider instance.

    Selection order:
      1. LLM_PROVIDER from config.py ("nvidia" | "gemini")
      2. HeuristicProvider if ENABLE_LLM_ANALYSIS is False
      3. HeuristicProvider if the configured provider fails to initialise
    """
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance

    if not ENABLE_LLM_ANALYSIS:
        logger.info("ENABLE_LLM_ANALYSIS=False — using HeuristicProvider.")
        _provider_instance = HeuristicProvider()
        return _provider_instance

    name = LLM_PROVIDER.lower().strip()
    constructors = {"nvidia": NvidiaProvider, "gemini": GeminiProvider}

    if name in constructors:
        try:
            _provider_instance = constructors[name]()
            return _provider_instance
        except Exception as exc:  # noqa: BLE001
            logger.error("%sProvider init failed: %s. Falling back to HeuristicProvider.", name.capitalize(), exc)
    else:
        logger.warning("Unknown LLM_PROVIDER '%s'. Falling back to HeuristicProvider.", LLM_PROVIDER)

    if not ENABLE_FALLBACK_ANALYSIS:
        raise RuntimeError(
            f"LLM provider '{LLM_PROVIDER}' failed and ENABLE_FALLBACK_ANALYSIS=False."
        )

    _provider_instance = HeuristicProvider()
    logger.info("HeuristicProvider active as fallback.")
    return _provider_instance


def reset_provider() -> None:
    """Force re-initialisation of the provider singleton. Useful for tests."""
    global _provider_instance
    _provider_instance = None
