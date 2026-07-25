"""
core/knowledge.py — Knowledge profile persistence for DocuWise (Phase 2).

Bridges the unified LLM analysis output (DocumentAnalysis dataclass) to the
knowledge_profiles table. This module owns:

  - Persisting a freshly-analyzed document's knowledge fields to the DB.
  - Serialising knowledge fields into the content_cache for future reuse.
  - Restoring knowledge fields from a cache entry into a document's profile.

All raw SQL lives in core.database — this module orchestrates persistence,
keeping data-access free of business logic (SRP).
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from core import database as db
from core.logging_events import log_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persist (analysis → knowledge_profiles table)
# ---------------------------------------------------------------------------

def persist_knowledge_profile(
    file_path: str,
    *,
    concepts: list[str],
    entities: list[dict],
    domains: list[str],
    doc_type: str = "",
    difficulty: str = "",
    prerequisites: list[str] | None = None,
    related_topics: list[str] | None = None,
    language: str = "",
    confidence: float = 0.5,
) -> bool:
    """
    Write a knowledge profile for the document at *file_path*.

    Looks up the document's integer ID, then upserts into knowledge_profiles.

    Args:
        file_path:       Absolute path identifying the document.
        concepts:        List of concept strings.
        entities:        List of entity dicts [{name, type}].
        domains:         List of domain strings.
        doc_type:        Document type classification.
        difficulty:      Difficulty level.
        prerequisites:   Prerequisite topic strings.
        related_topics:  Related topic strings.
        language:        ISO 639-1 language code.
        confidence:      Extraction confidence 0.0–1.0.

    Returns:
        True if the profile was persisted, False on any error.
    """
    doc = db.get_document(file_path)
    if doc is None:
        logger.warning("Cannot persist knowledge profile — document not found: '%s'", file_path)
        return False

    document_id: int = doc["id"]

    try:
        db.upsert_knowledge_profile(
            document_id,
            concepts_json=json.dumps(concepts) if concepts else "[]",
            entities_json=json.dumps(entities) if entities else "[]",
            domains_json=json.dumps(domains) if domains else "[]",
            doc_type=doc_type or None,
            difficulty=difficulty or None,
            prerequisites_json=json.dumps(prerequisites) if prerequisites else "[]",
            related_topics_json=json.dumps(related_topics) if related_topics else "[]",
            language=language or None,
            confidence=confidence,
        )
        log_event(
            logger, "KNOWLEDGE_PROFILE_SAVED",
            file=doc.get("filename"),
            concepts=len(concepts),
            entities=len(entities),
            domains=len(domains),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to persist knowledge profile for '%s': %s", file_path, exc
        )
        return False


# ---------------------------------------------------------------------------
# Serialise knowledge fields for content_cache upsert
# ---------------------------------------------------------------------------

def knowledge_fields_for_cache(
    *,
    concepts: list[str],
    entities: list[dict],
    domains: list[str],
    doc_type: str = "",
    difficulty: str = "",
    prerequisites: list[str] | None = None,
    related_topics: list[str] | None = None,
    language: str = "",
) -> dict[str, str | None]:
    """
    Return a dict of knowledge fields suitable for content_cache_upsert(**fields).

    Serialises lists/dicts to JSON strings. Keys match the content_cache
    column names added in Phase 2.
    """
    return {
        "concepts_json": json.dumps(concepts) if concepts else "[]",
        "entities_json": json.dumps(entities) if entities else "[]",
        "domains_json": json.dumps(domains) if domains else "[]",
        "doc_type": doc_type or None,
        "difficulty": difficulty or None,
        "prerequisites_json": json.dumps(prerequisites) if prerequisites else "[]",
        "related_topics_json": json.dumps(related_topics) if related_topics else "[]",
        "language": language or None,
    }


# ---------------------------------------------------------------------------
# Restore knowledge fields from a cache entry
# ---------------------------------------------------------------------------

def restore_knowledge_from_cache(file_path: str, entry: dict) -> bool:
    """
    Restore a knowledge profile from a content_cache *entry* for *file_path*.

    Called when a complete cache hit includes knowledge data (concepts_json
    is non-null). Looks up the document's ID and upserts the profile.

    Args:
        file_path: Absolute path of the document being restored.
        entry:     Content-cache dict with knowledge columns.

    Returns:
        True if the profile was restored, False otherwise.
    """
    # Only restore if the cache entry actually has knowledge data.
    if not (entry.get("concepts_json") or "").strip():
        return False

    doc = db.get_document(file_path)
    if doc is None:
        return False

    try:
        db.upsert_knowledge_profile(
            doc["id"],
            concepts_json=entry.get("concepts_json"),
            entities_json=entry.get("entities_json"),
            domains_json=entry.get("domains_json"),
            doc_type=entry.get("doc_type"),
            difficulty=entry.get("difficulty"),
            prerequisites_json=entry.get("prerequisites_json"),
            related_topics_json=entry.get("related_topics_json"),
            language=entry.get("language"),
            confidence=None,  # Confidence not stored in cache
        )
        log_event(logger, "KNOWLEDGE_PROFILE_RESTORED", file=doc.get("filename"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("Knowledge profile restore skipped for '%s': %s", file_path, exc)
        return False
