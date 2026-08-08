"""NLPP domain lesson seeding (P5)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = PROJECT_ROOT / "PythonScripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from SemanticMemory import (  # noqa: E402
    COLLECTION_CODING,
    _get_collection,
    add_memory,
)

DEFAULT_JSON = Path(__file__).resolve().parent.parent / "nlpp_lessons.json"
SOURCE = "seed_nlpp"


def _seed_exists(seed_id: str) -> bool:
    coll = _get_collection(COLLECTION_CODING)
    try:
        got = coll.get(where={"seed_id": seed_id}, include=[])
    except Exception:
        return False
    return bool(got.get("ids"))


def _store_lesson(row: dict[str, Any], *, force: bool = False) -> str | None:
    seed_id = str(row.get("seed_id") or "").strip()
    if not seed_id:
        raise ValueError("Lesson missing seed_id")

    if not force and _seed_exists(seed_id):
        return None

    user_prompt = str(row.get("user_prompt") or row.get("topic") or seed_id)
    answer = str(row.get("answer") or "").strip()
    importance = int(row.get("importance") or 8)
    topic = str(row.get("topic") or seed_id)

    lesson_text = (
        f"[NLPP domain seed: {topic}]\n"
        f"User ask: {user_prompt.strip()[:500]}\n"
        f"Working solution ({SOURCE}/{seed_id}):\n{answer[:4000]}"
    )
    return add_memory(
        lesson_text,
        importance_score=importance,
        metadata={
            "source": SOURCE,
            "kind": "coding_lesson",
            "seed_id": seed_id,
            "topic": topic,
        },
        collection=COLLECTION_CODING,
    )


def seed_all(
    json_path: Path | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    path = json_path or DEFAULT_JSON
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"{path} must be a JSON array")

    inserted: list[str] = []
    skipped: list[str] = []
    for row in rows:
        seed_id = str(row.get("seed_id") or "")
        mid = _store_lesson(row, force=force)
        if mid:
            inserted.append(seed_id)
        else:
            skipped.append(seed_id)
    return {"inserted": inserted, "skipped": skipped, "total": len(rows)}
