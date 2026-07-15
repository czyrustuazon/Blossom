"""
Correctness feedback for coding + Japanese-teaching routes (not companionship).

Pending turns are keyed by feedback_id so clients can thumbs-up / thumbs-down
after a reply without resending the full Q&A.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from typing import Any

from MemoryUpdater import DB_PATH
from SemanticMemory import (
    COLLECTION_CODING,
    COLLECTION_LANGUAGE,
    add_memory,
    delete_memory,
    get_memory,
    learn_coding_lesson,
    learn_language_lesson,
    set_memory_importance,
    update_memory_metadata,
)

logger = logging.getLogger(__name__)

FEEDBACK_TTL_SEC = 7 * 24 * 3600
VALID_ROUTES = frozenset({"coding", "japanese"})
VALID_VERDICTS = frozenset({"correct", "incorrect"})


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_feedback_table() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback_turns (
                id TEXT PRIMARY KEY,
                route TEXT NOT NULL,
                user_prompt TEXT NOT NULL,
                answer TEXT NOT NULL,
                source TEXT,
                memory_id TEXT,
                collection TEXT,
                verdict TEXT,
                note TEXT,
                result_json TEXT,
                created_at REAL NOT NULL,
                resolved_at REAL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_turns_created "
            "ON feedback_turns(created_at)"
        )
        conn.commit()
    finally:
        conn.close()


def _prune_old(conn: sqlite3.Connection) -> None:
    cutoff = time.time() - FEEDBACK_TTL_SEC
    conn.execute("DELETE FROM feedback_turns WHERE created_at < ?", (cutoff,))


def register_feedback_turn(
    *,
    route: str,
    user_prompt: str,
    answer: str,
    source: str = "",
    memory_id: str | None = None,
    collection: str | None = None,
) -> str | None:
    """
    Record a feedbackable reply. Returns feedback_id, or None if the route
    should not accept correctness feedback (e.g. casual companionship).
    """
    route_key = (route or "").strip().lower()
    if route_key not in VALID_ROUTES:
        return None
    prompt = (user_prompt or "").strip()
    text = (answer or "").strip()
    if not prompt or not text:
        return None

    if collection is None:
        collection = (
            COLLECTION_CODING if route_key == "coding" else COLLECTION_LANGUAGE
        )

    ensure_feedback_table()
    feedback_id = str(uuid.uuid4())
    conn = _connect()
    try:
        _prune_old(conn)
        conn.execute(
            """
            INSERT INTO feedback_turns (
                id, route, user_prompt, answer, source, memory_id, collection,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feedback_id,
                route_key,
                prompt[:8000],
                text[:12000],
                (source or "")[:200],
                memory_id,
                collection,
                time.time(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return feedback_id


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def apply_correctness_feedback(
    feedback_id: str,
    verdict: str,
    note: str | None = None,
) -> dict[str, Any]:
    """
    Apply user correctness judgment.

    coding + correct:
      boost existing lesson importance, or learn a new coding_lessons row
    coding + incorrect:
      delete the auto-saved lesson (if any); optional note stored as caution
    japanese + correct:
      learn into language_lessons (gated — only on thumbs-up)
    japanese + incorrect:
      no template save; optional note stored as correction caution
    """
    ensure_feedback_table()
    fid = (feedback_id or "").strip()
    verd = (verdict or "").strip().lower()
    if verd in {"up", "good", "right", "yes", "true", "1"}:
        verd = "correct"
    elif verd in {"down", "bad", "wrong", "no", "false", "0"}:
        verd = "incorrect"
    if verd not in VALID_VERDICTS:
        raise ValueError("verdict must be 'correct' or 'incorrect'")
    if not fid:
        raise ValueError("feedback_id is required")

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM feedback_turns WHERE id = ?", (fid,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown feedback_id: {fid}")
        turn = _row_to_dict(row)
        if turn.get("verdict"):
            prior = {}
            raw = turn.get("result_json")
            if raw:
                try:
                    prior = json.loads(raw)
                except json.JSONDecodeError:
                    prior = {}
            return {
                "ok": True,
                "already_resolved": True,
                "feedback_id": fid,
                "route": turn["route"],
                "verdict": turn["verdict"],
                **prior,
            }

        result = _resolve_turn(turn, verd, (note or "").strip())
        conn.execute(
            """
            UPDATE feedback_turns
            SET verdict = ?, note = ?, result_json = ?, resolved_at = ?
            WHERE id = ?
            """,
            (
                verd,
                (note or "").strip()[:2000] or None,
                json.dumps(result, ensure_ascii=False),
                time.time(),
                fid,
            ),
        )
        conn.commit()
        return {
            "ok": True,
            "already_resolved": False,
            "feedback_id": fid,
            "route": turn["route"],
            "verdict": verd,
            **result,
        }
    finally:
        conn.close()


def _resolve_turn(
    turn: dict[str, Any],
    verdict: str,
    note: str,
) -> dict[str, Any]:
    route = turn["route"]
    user_prompt = turn["user_prompt"] or ""
    answer = turn["answer"] or ""
    source = turn.get("source") or "feedback"
    memory_id = turn.get("memory_id") or None
    collection = turn.get("collection") or (
        COLLECTION_CODING if route == "coding" else COLLECTION_LANGUAGE
    )

    if route == "coding":
        return _resolve_coding(
            verdict=verdict,
            note=note,
            user_prompt=user_prompt,
            answer=answer,
            source=source,
            memory_id=memory_id,
            collection=collection,
        )
    return _resolve_japanese(
        verdict=verdict,
        note=note,
        user_prompt=user_prompt,
        answer=answer,
        source=source,
    )


def _resolve_coding(
    *,
    verdict: str,
    note: str,
    user_prompt: str,
    answer: str,
    source: str,
    memory_id: str | None,
    collection: str,
) -> dict[str, Any]:
    actions: list[str] = []
    new_ids: list[str] = []

    if verdict == "correct":
        if memory_id and get_memory(memory_id, collection=collection):
            set_memory_importance(memory_id, collection=collection, importance=9)
            update_memory_metadata(
                memory_id,
                collection=collection,
                patch={"user_verified": True, "feedback": "correct"},
            )
            actions.append("boosted_coding_lesson")
            return {
                "actions": actions,
                "memory_id": memory_id,
                "stored": True,
            }
        mid = learn_coding_lesson(
            user_prompt,
            answer,
            source=f"{source}+user_verified",
            importance_score=9,
        )
        if mid:
            update_memory_metadata(
                mid,
                collection=COLLECTION_CODING,
                patch={"user_verified": True, "feedback": "correct"},
            )
            actions.append("learned_coding_lesson")
            new_ids.append(mid)
            return {
                "actions": actions,
                "memory_id": mid,
                "memory_ids": new_ids,
                "stored": True,
            }
        actions.append("skipped_empty_or_weak")
        return {"actions": actions, "stored": False}

    # incorrect
    if memory_id:
        if delete_memory(memory_id, collection=collection):
            actions.append("deleted_coding_lesson")
        else:
            actions.append("memory_already_gone")
    if note:
        caution = (
            f"User marked a coding answer incorrect.\n"
            f"Ask: {user_prompt[:400]}\n"
            f"Correction note: {note[:1500]}"
        )
        mid = add_memory(
            caution[:3500],
            importance_score=7,
            metadata={
                "source": f"{source}+user_rejected",
                "kind": "coding_caution",
                "feedback": "incorrect",
            },
            collection=COLLECTION_CODING,
        )
        actions.append("stored_coding_caution")
        new_ids.append(mid)
        return {
            "actions": actions,
            "memory_id": mid,
            "memory_ids": new_ids,
            "stored": True,
            "deleted": bool(memory_id),
        }
    return {
        "actions": actions or ["recorded_incorrect"],
        "stored": False,
        "deleted": bool(memory_id),
    }


def _resolve_japanese(
    *,
    verdict: str,
    note: str,
    user_prompt: str,
    answer: str,
    source: str,
) -> dict[str, Any]:
    actions: list[str] = []

    if verdict == "correct":
        mid = learn_language_lesson(
            user_prompt,
            answer,
            source=f"{source}+user_verified",
            note=note or None,
            importance_score=8,
        )
        if mid:
            actions.append("learned_language_lesson")
            return {
                "actions": actions,
                "memory_id": mid,
                "stored": True,
            }
        actions.append("skipped_empty_or_weak")
        return {"actions": actions, "stored": False}

    if note:
        body = (
            f"(Marked incorrect by user.)\n"
            f"Ask: {user_prompt[:300]}\n"
            f"Correction: {note[:1500]}"
        )
        mid = learn_language_lesson(
            user_prompt,
            body,
            source=f"{source}+user_rejected",
            note=note,
            importance_score=7,
            kind="language_caution",
        )
        if not mid:
            mid = add_memory(
                body[:3500],
                importance_score=7,
                metadata={
                    "source": f"{source}+user_rejected",
                    "kind": "language_caution",
                    "feedback": "incorrect",
                },
                collection=COLLECTION_LANGUAGE,
            )
        if mid:
            actions.append("stored_language_caution")
            return {
                "actions": actions,
                "memory_id": mid,
                "stored": True,
            }
    actions.append("recorded_incorrect_no_store")
    return {"actions": actions, "stored": False}
