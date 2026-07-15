"""
Long-term semantic memories in ChromaDB (local persistent vectors).

Collections:
  - relationship_life  : personal / relationship memories
  - coding_lessons     : bugs, fixes, Gemini/local coding takeaways
  - language_lessons   : Japanese-teaching facts (user-verified)
  - web_knowledge      : useful findings learned from web search
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
load_dotenv(SCRIPT_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

MIND_DIR = PROJECT_ROOT / "Mind"
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", str(MIND_DIR / "chromadb")))
COLLECTION_LIFE = os.getenv("CHROMA_COLLECTION_LIFE", "relationship_life")
COLLECTION_CODING = os.getenv("CHROMA_COLLECTION_CODING", "coding_lessons")
COLLECTION_LANGUAGE = os.getenv("CHROMA_COLLECTION_LANGUAGE", "language_lessons")
COLLECTION_WEB = os.getenv("CHROMA_COLLECTION_WEB", "web_knowledge")
# Back-compat alias used by older code/docs
MEMORY_COLLECTION = COLLECTION_LIFE
MEMORY_TOP_K = max(1, int(os.getenv("MEMORY_TOP_K", "5")))
# Skip memories demoted below this importance when querying.
MEMORY_MIN_IMPORTANCE = max(0, int(os.getenv("MEMORY_MIN_IMPORTANCE", "2")))

logger = logging.getLogger(__name__)

_client = None
_collections: dict[str, Any] = {}


def _get_client():
    global _client
    if _client is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
    return _client


def _get_collection(name: str):
    if name not in _collections:
        _collections[name] = _get_client().get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
    return _collections[name]


def add_memory(
    memory_text: str,
    importance_score: int = 5,
    metadata: dict[str, Any] | None = None,
    collection: str = COLLECTION_LIFE,
) -> str:
    """Embed and store one long-term memory. Returns the memory id."""
    text = (memory_text or "").strip()
    if not text:
        raise ValueError("memory_text is empty")

    memory_id = str(uuid.uuid4())
    meta: dict[str, Any] = {
        "importance_score": int(importance_score),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "collection": collection,
    }
    if metadata:
        for key, value in metadata.items():
            meta[str(key)] = (
                value if isinstance(value, (str, int, float, bool)) else str(value)
            )

    coll = _get_collection(collection)
    coll.add(ids=[memory_id], documents=[text], metadatas=[meta])
    logger.info(
        "Stored memory %s in %s (importance=%s)",
        memory_id,
        collection,
        importance_score,
    )
    return memory_id


def query_memories(
    query_text: str,
    top_k: int | None = None,
    collection: str = COLLECTION_LIFE,
) -> list[dict[str, Any]]:
    """Return the most relevant long-term memories for a query.

    Fetches a wider candidate set, drops low-importance / rejected rows, then
    ranks by importance (desc) and distance (asc).
    """
    text = (query_text or "").strip()
    if not text:
        return []

    n = top_k or MEMORY_TOP_K
    coll = _get_collection(collection)
    count = coll.count()
    if count == 0:
        return []

    fetch_n = min(count, max(n * 3, n))
    result = coll.query(
        query_texts=[text],
        n_results=fetch_n,
        include=["documents", "metadatas", "distances"],
    )

    memories = []
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    ids = (result.get("ids") or [[]])[0]

    for memory_id, document, meta, distance in zip(ids, documents, metadatas, distances):
        meta = meta or {}
        if meta.get("rejected") is True or str(meta.get("rejected", "")).lower() in {
            "true",
            "1",
            "yes",
        }:
            continue
        try:
            importance = int(meta.get("importance_score", 5))
        except (TypeError, ValueError):
            importance = 5
        if importance < MEMORY_MIN_IMPORTANCE:
            continue
        memories.append(
            {
                "id": memory_id,
                "text": document,
                "metadata": meta,
                "distance": distance,
                "importance": importance,
            }
        )

    memories.sort(key=lambda m: (-m["importance"], m["distance"] if m["distance"] is not None else 9.0))
    return memories[:n]


def get_memory(
    memory_id: str,
    *,
    collection: str = COLLECTION_LIFE,
) -> dict[str, Any] | None:
    mid = (memory_id or "").strip()
    if not mid:
        return None
    coll = _get_collection(collection)
    try:
        got = coll.get(ids=[mid], include=["documents", "metadatas"])
    except Exception:
        return None
    ids = got.get("ids") or []
    if not ids:
        return None
    docs = got.get("documents") or []
    metas = got.get("metadatas") or []
    return {
        "id": ids[0],
        "text": docs[0] if docs else "",
        "metadata": metas[0] if metas else {},
    }


def delete_memory(
    memory_id: str,
    *,
    collection: str = COLLECTION_LIFE,
) -> bool:
    mid = (memory_id or "").strip()
    if not mid:
        return False
    coll = _get_collection(collection)
    try:
        existing = coll.get(ids=[mid], include=[])
        if not (existing.get("ids") or []):
            return False
        coll.delete(ids=[mid])
        logger.info("Deleted memory %s from %s", mid, collection)
        return True
    except Exception:
        logger.exception("Failed to delete memory %s from %s", mid, collection)
        return False


def set_memory_importance(
    memory_id: str,
    *,
    collection: str,
    importance: int,
) -> bool:
    return update_memory_metadata(
        memory_id,
        collection=collection,
        patch={"importance_score": int(max(1, min(10, importance)))},
    )


def update_memory_metadata(
    memory_id: str,
    *,
    collection: str,
    patch: dict[str, Any],
) -> bool:
    mid = (memory_id or "").strip()
    if not mid or not patch:
        return False
    existing = get_memory(mid, collection=collection)
    if not existing:
        return False
    meta = dict(existing.get("metadata") or {})
    for key, value in patch.items():
        meta[str(key)] = (
            value if isinstance(value, (str, int, float, bool)) else str(value)
        )
    coll = _get_collection(collection)
    try:
        coll.update(ids=[mid], metadatas=[meta])
        return True
    except Exception:
        logger.exception("Failed to update metadata for %s in %s", mid, collection)
        return False


def format_memories_for_prompt(
    memories: list[dict[str, Any]],
    heading: str = "[LONG-TERM SEMANTIC MEMORIES]",
) -> str:
    if not memories:
        return ""
    lines = [heading]
    for index, memory in enumerate(memories, start=1):
        lines.append(f"{index}. {memory['text']}")
    return "\n".join(lines)


def looks_useful_answer(text: str) -> bool:
    """Heuristic: keep Gemini/local answers that look substantive."""
    cleaned = (text or "").strip()
    if len(cleaned) < 40:
        return False
    lowered = cleaned.lower()
    reject_markers = (
        "i can't help",
        "i cannot help",
        "as an ai",
        "no api key",
        "rate limit",
        "timed out",
        "unavailable",
    )
    return not any(marker in lowered for marker in reject_markers)


def learn_coding_lesson(
    user_prompt: str,
    answer: str,
    source: str,
    importance_score: int = 6,
) -> str | None:
    """Persist a useful coding takeaway so the local coder can retrieve it later."""
    if not looks_useful_answer(answer):
        logger.info("Skipped coding lesson save from %s (not useful enough).", source)
        return None
    lesson = (
        f"User ask: {user_prompt.strip()[:500]}\n"
        f"Working solution ({source}):\n{answer.strip()[:4000]}"
    )
    return add_memory(
        lesson,
        importance_score=importance_score,
        metadata={"source": source, "kind": "coding_lesson"},
        collection=COLLECTION_CODING,
    )


def learn_language_lesson(
    user_prompt: str,
    answer: str,
    source: str,
    *,
    note: str | None = None,
    importance_score: int = 8,
    kind: str = "language_lesson",
) -> str | None:
    """
    Persist a Japanese-teaching takeaway (user-verified preferred).
    Stores ask + compact teaching notes — not a full reply template.
    """
    ask = (user_prompt or "").strip()
    body = (answer or "").strip()
    extra = (note or "").strip()
    if len(ask) < 3 or len(body) < 20:
        logger.info("Skipped language lesson save from %s (too short).", source)
        return None
    # Prefer a compact blob so RAG injects facts, not personality echo.
    lesson = (
        f"Japanese study ask: {ask[:400]}\n"
        f"Verified notes ({source}):\n{body[:2500]}"
    )
    if extra:
        lesson += f"\nUser note: {extra[:500]}"
    return add_memory(
        lesson,
        importance_score=importance_score,
        metadata={
            "source": source,
            "kind": kind,
            "user_verified": kind == "language_lesson",
        },
        collection=COLLECTION_LANGUAGE,
    )


def learn_web_findings(
    query: str,
    results: list[dict[str, Any]],
    *,
    summary: str | None = None,
    source_provider: str = "web",
) -> list[str]:
    """
    Store web search hits (and optional LLM summary) into web_knowledge.
    Returns list of created memory ids.
    """
    ids: list[str] = []
    if summary and looks_useful_answer(summary):
        ids.append(
            add_memory(
                f"Web research query: {query.strip()[:300]}\nSummary:\n{summary.strip()[:4000]}",
                importance_score=6,
                metadata={
                    "source": source_provider,
                    "kind": "web_summary",
                    "query": query[:200],
                },
                collection=COLLECTION_WEB,
            )
        )

    for item in results[:5]:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if not snippet and not title:
            continue
        text = (
            f"Source: {title or url}\n"
            f"URL: {url}\n"
            f"Notes: {snippet}"
        ).strip()
        if len(text) < 40:
            continue
        ids.append(
            add_memory(
                text[:3500],
                importance_score=5,
                metadata={
                    "source": source_provider,
                    "kind": "web_result",
                    "url": url[:500],
                    "query": query[:200],
                },
                collection=COLLECTION_WEB,
            )
        )
    if ids:
        logger.info("Stored %s web knowledge memories for query=%r", len(ids), query[:80])
    return ids


def migrate_sqlite_semantic_memories() -> int:
    """One-time copy of old SQLite semantic_memories rows into relationship_life."""
    from MemoryUpdater import DB_PATH

    if not DB_PATH.exists():
        return 0

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='semantic_memories'"
        )
        if cursor.fetchone() is None:
            return 0

        cursor.execute(
            "SELECT id, memory_text, importance_score, created_at "
            "FROM semantic_memories ORDER BY id ASC"
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        return 0

    # Also migrate legacy single Chroma collection if present
    client = _get_client()
    try:
        legacy = client.get_collection("semantic_memories")
        legacy_data = legacy.get(include=["documents", "metadatas"])
        life = _get_collection(COLLECTION_LIFE)
        existing = set(life.get(include=[]).get("ids") or [])
        moved = 0
        for legacy_id, doc, meta in zip(
            legacy_data.get("ids") or [],
            legacy_data.get("documents") or [],
            legacy_data.get("metadatas") or [],
        ):
            new_id = f"legacy-chroma-{legacy_id}"
            if new_id in existing or not (doc or "").strip():
                continue
            life.add(
                ids=[new_id],
                documents=[doc],
                metadatas=[{**(meta or {}), "migrated_from": "chroma_semantic_memories"}],
            )
            moved += 1
        if moved:
            logger.info("Migrated %s rows from legacy chroma collection.", moved)
    except Exception:
        pass

    collection = _get_collection(COLLECTION_LIFE)
    existing = set(collection.get(include=[]).get("ids") or [])
    migrated = 0

    for row_id, memory_text, importance_score, created_at in rows:
        legacy_id = f"sqlite-{row_id}"
        if legacy_id in existing:
            continue
        text = (memory_text or "").strip()
        if not text:
            continue
        collection.add(
            ids=[legacy_id],
            documents=[text],
            metadatas=[
                {
                    "importance_score": int(importance_score or 5),
                    "created_at": created_at or "",
                    "migrated_from": "sqlite",
                }
            ],
        )
        migrated += 1

    if migrated:
        logger.info(
            "Migrated %s semantic memories from SQLite into %s.",
            migrated,
            COLLECTION_LIFE,
        )
    return migrated
