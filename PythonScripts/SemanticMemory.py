"""
Long-term semantic memories in ChromaDB (local persistent vectors).

Collections and the client store that owns them:
  - relationship_life  : personal / relationship memories          (companion)
  - language_lessons   : Japanese-teaching facts (user-verified)   (companion)
  - coding_lessons     : general + NLPP lessons + product manuals  (assistant)
  - nlpp_hard_bans     : critical NLPP bans (always retrieved on coding) (assistant)
  - web_knowledge      : findings learned from web search          (per client)

A collection is only reachable from its home surface: cross-surface reads return
nothing and writes are dropped, so Assistant lessons never reach Haruhi's prompt.

coding_lessons metadata taxonomy:
  - scope: general | product | nlpp | learned
  - group: process | security-ops | data | ml-local | architecture | nlpp-re | product-manual | learned
  - family: cross-project | homelab-media | local-diffusion | appsec | nlpp-re | decomp-matching
  - product: optional project id (anime-db-stream, waifu-redraw, decomp-matching, …)
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import threading

import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv

import MindStores
from MindStores import SURFACE_ASSISTANT, SURFACE_COMPANION, current_surface

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
load_dotenv(SCRIPT_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

COLLECTION_LIFE = os.getenv("CHROMA_COLLECTION_LIFE", "relationship_life")
COLLECTION_CODING = os.getenv("CHROMA_COLLECTION_CODING", "coding_lessons")
COLLECTION_HARD_BANS = os.getenv("CHROMA_COLLECTION_HARD_BANS", "nlpp_hard_bans")
COLLECTION_LANGUAGE = os.getenv("CHROMA_COLLECTION_LANGUAGE", "language_lessons")
COLLECTION_WEB = os.getenv("CHROMA_COLLECTION_WEB", "web_knowledge")
# Back-compat alias used by older code/docs
MEMORY_COLLECTION = COLLECTION_LIFE
MEMORY_TOP_K = max(1, int(os.getenv("MEMORY_TOP_K", "5")))
# Coding path: hard bans always + broader lesson recall than default MEMORY_TOP_K.
HARD_BANS_TOP_K = max(1, int(os.getenv("HARD_BANS_TOP_K", "5")))
CODING_LESSONS_TOP_K = max(1, int(os.getenv("CODING_LESSONS_TOP_K", "10")))
HARD_BANS_PROMPT_MAX_CHARS = max(400, int(os.getenv("HARD_BANS_PROMPT_MAX_CHARS", "2200")))
# Skip memories demoted below this importance when querying.
MEMORY_MIN_IMPORTANCE = max(0, int(os.getenv("MEMORY_MIN_IMPORTANCE", "2")))
MEMORY_PROMPT_MAX_CHARS = max(500, int(os.getenv("MEMORY_PROMPT_MAX_CHARS", "4000")))

logger = logging.getLogger(__name__)

LEGACY_SEMANTIC_COLLECTION = "semantic_memories"
# None = every surface keeps its own copy (web research).
COLLECTION_HOME: dict[str, str | None] = {
    COLLECTION_LIFE: SURFACE_COMPANION,
    COLLECTION_LANGUAGE: SURFACE_COMPANION,
    LEGACY_SEMANTIC_COLLECTION: SURFACE_COMPANION,
    COLLECTION_CODING: SURFACE_ASSISTANT,
    COLLECTION_HARD_BANS: SURFACE_ASSISTANT,
    COLLECTION_WEB: None,
}

_clients: dict[str, Any] = {}
_collections: dict[tuple[str, str], Any] = {}
_clients_lock = threading.Lock()


def collection_home(name: str) -> str | None:
    return COLLECTION_HOME.get(name, SURFACE_COMPANION)


def store_surface_for(name: str, surface: str | None = None) -> str | None:
    """Which surface's Chroma dir serves this collection right now (None = denied).

    Without an active surface (seed scripts, maintenance), home-owned collections
    resolve to their home; per-client collections need an explicit surface.
    """
    active = surface or current_surface()
    home = collection_home(name)
    if home is None:
        return active
    if active is None or active == home:
        return home
    return None


def _get_client(surface: str):
    path = MindStores.chroma_dir(surface)
    key = str(path)
    with _clients_lock:
        client = _clients.get(key)
        if client is None:
            path.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(
                path=key,
                settings=Settings(anonymized_telemetry=False),
            )
            _clients[key] = client
        return client


def _get_collection(name: str, *, surface: str | None = None):
    """Collection handle, or None when the active surface may not touch it."""
    store = store_surface_for(name, surface)
    if store is None:
        logger.debug(
            "Collection %s is not reachable from surface %s", name, surface or current_surface()
        )
        return None
    key = (str(MindStores.chroma_dir(store)), name)
    coll = _collections.get(key)
    if coll is None:
        coll = _get_client(store).get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
        _collections[key] = coll
    return coll


def reset_clients() -> None:
    """Drop cached Chroma handles (tests / after store moves)."""
    with _clients_lock:
        _collections.clear()
        _clients.clear()
        try:
            from chromadb.api.client import SharedSystemClient

            SharedSystemClient.clear_system_cache()
        except Exception:
            pass


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
    if coll is None:
        logger.warning(
            "Dropped write to %s: not owned by surface %s", collection, current_surface()
        )
        return ""
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
    if coll is None:
        return []
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


def _infer_scope(meta: dict[str, Any]) -> str:
    scope = str(meta.get("scope") or "").strip().lower()
    if scope:
        return scope
    product = str(meta.get("product") or "").strip().lower()
    batch = str(meta.get("seed_batch") or "").strip().lower()
    source = str(meta.get("source") or "").strip().lower()
    seed_id = str(meta.get("seed_id") or "").strip().lower()
    if product == "general":
        return "general"
    if (
        batch in {"seed_chroma_nlpp", "seed_nlpp"}
        or source in {"seed_nlpp", "seed_chroma_nlpp"}
        or str(meta.get("family") or "") == "nlpp-re"
        or seed_id.startswith("nlpp-")
        or seed_id.startswith("ban-")
    ):
        return "nlpp"
    if product:
        return "product"
    return "learned"


def query_coding_lessons(
    query_text: str,
    *,
    top_k: int | None = None,
    path_hints: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve coding lessons preferring general/NLPP + workspace-matched products.

    Product manuals for unrelated families are dropped so shared RAG stays useful
    across many projects.
    """
    n = top_k or CODING_LESSONS_TOP_K
    # Wider candidate pool so filtering still leaves enough hits.
    raw = query_memories(query_text, top_k=max(n * 6, n), collection=COLLECTION_CODING)
    if not raw:
        return []

    allowed_products: set[str] = set()
    # Always keep cross-project generals. NLPP/product families require a workspace match.
    allowed_families: set[str] = {"cross-project"}
    try:
        seed_catalog = (
            PROJECT_ROOT / "tools" / "seed" / "blossom_seed" / "catalog.py"
        )
        if seed_catalog.is_file():
            import sys

            seed_root = str(PROJECT_ROOT / "tools" / "seed")
            if seed_root not in sys.path:
                sys.path.insert(0, seed_root)
            from blossom_seed.catalog import (  # type: ignore
                infer_workspace_targets,
                load_catalog,
            )

            products, families = infer_workspace_targets(path_hints, load_catalog())
            allowed_products |= products
            allowed_families |= families
    except Exception as exc:
        logger.debug("coding lesson taxonomy filter unavailable: %s", exc)
        # Heuristic fallback from path hints alone
        blob = " ".join(path_hints or []).lower().replace("\\", "/")
        for needle, family in (
            ("anime-db-stream", "homelab-media"),
            ("anime-db-tracker", "homelab-media"),
            ("waifu redraw", "local-diffusion"),
            ("waifu-redraw", "local-diffusion"),
            ("instagram model ai", "local-diffusion"),
            ("animewallpaper", "local-diffusion"),
            ("trace-viper", "appsec"),
            ("pen-tester", "appsec"),
            ("img.bin", "nlpp-re"),
            ("layeredfs", "nlpp-re"),
            ("nlpp", "nlpp-re"),
            ("decomp", "decomp-matching"),
            ("ctrdecomp", "decomp-matching"),
            ("code.bin", "decomp-matching"),
            ("matching-decomp", "decomp-matching"),
        ):
            if needle in blob:
                allowed_families.add(family)

    kept: list[dict[str, Any]] = []
    for row in raw:
        meta = dict(row.get("metadata") or {})
        scope = _infer_scope(meta)
        product = str(meta.get("product") or "").strip().lower()
        family = str(meta.get("family") or "").strip().lower()
        if scope == "general":
            row = dict(row)
            row["importance"] = int(row.get("importance") or 5) + 1
            kept.append(row)
            continue
        if scope == "learned":
            kept.append(row)
            continue
        if scope == "nlpp":
            if "nlpp-re" in allowed_families:
                kept.append(row)
            continue
        if scope == "product":
            if product and product in allowed_products:
                kept.append(row)
                continue
            if family and family in allowed_families:
                kept.append(row)
                continue
            # Unmatched product manuals stay out of the shared pool.
            continue
        kept.append(row)

    kept.sort(
        key=lambda m: (
            -int(m.get("importance") or 5),
            m.get("distance") if m.get("distance") is not None else 9.0,
        )
    )
    return kept[:n]


def get_memory(
    memory_id: str,
    *,
    collection: str = COLLECTION_LIFE,
) -> dict[str, Any] | None:
    mid = (memory_id or "").strip()
    if not mid:
        return None
    coll = _get_collection(collection)
    if coll is None:
        return None
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
    if coll is None:
        return False
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
    if coll is None:
        return False
    try:
        coll.update(ids=[mid], metadatas=[meta])
        return True
    except Exception:
        logger.exception("Failed to update metadata for %s in %s", mid, collection)
        return False


from TemporalContext import relative_age


def format_memories_for_prompt(
    memories: list[dict[str, Any]],
    heading: str = "[LONG-TERM SEMANTIC MEMORIES]",
    *,
    max_chars: int | None = None,
) -> str:
    if not memories:
        return ""
    budget = max_chars if max_chars is not None else MEMORY_PROMPT_MAX_CHARS
    lines = [heading]
    used = len(heading)
    omitted = 0
    for index, memory in enumerate(memories, start=1):
        meta = memory.get("metadata") or {}
        age = relative_age(meta.get("created_at"))
        prefix = f"({age}) " if age else ""
        line = f"{index}. {prefix}{memory['text']}"
        if used + len(line) + 1 > budget:
            omitted = len(memories) - index + 1
            break
        lines.append(line)
        used += len(line) + 1
    if omitted:
        lines.append(f"… ({omitted} more lesson(s) omitted for token budget)")
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
    ids = [mid for mid in ids if mid]
    if ids:
        logger.info("Stored %s web knowledge memories for query=%r", len(ids), query[:80])
    return ids


def migrate_sqlite_semantic_memories() -> int:
    """One-time copy of old SQLite semantic_memories rows into Companion's relationship_life."""
    db = MindStores.db_path(SURFACE_COMPANION)
    if not db.exists():
        return 0

    conn = sqlite3.connect(db)
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

    collection = _get_collection(COLLECTION_LIFE, surface=SURFACE_COMPANION)
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


def _copy_collection(src_coll, dst_coll, batch: int = 200) -> int:
    existing = set(dst_coll.get(include=[]).get("ids") or [])
    data = src_coll.get(include=["documents", "metadatas", "embeddings"])
    ids = data.get("ids") or []
    docs = data.get("documents") or []
    metas = data.get("metadatas") or []
    embs = data.get("embeddings")
    copied = 0
    for start in range(0, len(ids), batch):
        chunk = [
            i for i in range(start, min(start + batch, len(ids))) if ids[i] not in existing
        ]
        if not chunk:
            continue
        kwargs: dict[str, Any] = {
            "ids": [ids[i] for i in chunk],
            "documents": [docs[i] for i in chunk],
            "metadatas": [metas[i] or {"migrated_from": "shared_store"} for i in chunk],
        }
        if embs is not None and len(embs) == len(ids):
            kwargs["embeddings"] = [embs[i] for i in chunk]
        dst_coll.add(**kwargs)
        copied += len(chunk)
    return copied


def split_legacy_collections() -> dict[str, int]:
    """Move companion-home collections out of the (formerly shared) Assistant store.

    The legacy Chroma dir was moved wholesale to Mind/assistant/chromadb; anything
    that belongs to Companion is copied over and then dropped from Assistant.
    Idempotent: a second run finds nothing left to move.
    """
    moved: dict[str, int] = {}
    src_dir = MindStores.chroma_dir(SURFACE_ASSISTANT)
    if not src_dir.is_dir():
        migrate_sqlite_semantic_memories()
        return moved
    src_client = _get_client(SURFACE_ASSISTANT)
    present = {getattr(c, "name", c) for c in src_client.list_collections()}
    for name, home in COLLECTION_HOME.items():
        if home != SURFACE_COMPANION or name not in present:
            continue
        src = src_client.get_collection(name)
        target = COLLECTION_LIFE if name == LEGACY_SEMANTIC_COLLECTION else name
        dst = _get_collection(target, surface=SURFACE_COMPANION)
        moved[target] = moved.get(target, 0) + _copy_collection(src, dst)
        src_client.delete_collection(name)
        _collections.pop((str(src_dir), name), None)
    migrate_sqlite_semantic_memories()
    if any(moved.values()):
        logger.info("Split Chroma collections into the Companion store: %s", moved)
    return moved
