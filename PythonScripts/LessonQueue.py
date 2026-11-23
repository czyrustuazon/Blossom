"""
Pending queue for auto-learned coding lessons.

The router used to write every "useful-looking" coder answer straight into the coding_lessons
vector store, where later prompts retrieved it as a "Working solution". Several of those were
non-answers ("Let me start by examining…") that taught the coder to announce and stop. Now a
lesson waits here until it is reviewed (PythonScripts/review_lessons.py); only approved
lessons reach the Mind.

Storage: SQLite at Mind/assistant/lesson_queue.db (coding lessons live in the Assistant Mind).
LESSON_QUEUE=0 turns the queue off (lessons are stored directly, the old behaviour).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import MindStores
from MindStores import SURFACE_ASSISTANT

QUEUED_PREFIX = "queued:"


def queue_enabled() -> bool:
    raw = (os.getenv("LESSON_QUEUE") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def is_queued_id(memory_id: str | None) -> bool:
    return bool(memory_id) and str(memory_id).startswith(QUEUED_PREFIX)


def _queue_id(memory_id: str) -> str:
    return str(memory_id)[len(QUEUED_PREFIX):] if is_queued_id(memory_id) else str(memory_id)


def db_file() -> Path:
    return MindStores.mind_dir(SURFACE_ASSISTANT) / "lesson_queue.db"


def _connect() -> sqlite3.Connection:
    path = db_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS lesson_queue (
            id TEXT PRIMARY KEY,
            created REAL NOT NULL,
            collection TEXT NOT NULL,
            text TEXT NOT NULL,
            metadata TEXT NOT NULL,
            importance INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewed REAL,
            reason TEXT,
            memory_id TEXT
        )"""
    )
    return conn


def enqueue(text: str, *, collection: str, importance: int, metadata: dict[str, Any]) -> str:
    """Add a lesson for review. Returns 'queued:<id>' (callers treat it like a memory id)."""
    qid = uuid.uuid4().hex[:12]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO lesson_queue (id, created, collection, text, metadata, importance) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (qid, time.time(), collection, text, json.dumps(metadata), int(importance)),
        )
    return QUEUED_PREFIX + qid


def _row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["metadata"] = json.loads(d.get("metadata") or "{}")
    return d


def list_entries(status: str | None = "pending") -> list[dict[str, Any]]:
    with _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM lesson_queue WHERE status = ? ORDER BY created", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM lesson_queue ORDER BY created").fetchall()
    return [_row(r) for r in rows]


def get_entry(memory_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM lesson_queue WHERE id = ?", (_queue_id(memory_id),)
        ).fetchone()
    return _row(row) if row else None


def mark_verified(memory_id: str) -> bool:
    """User said the answer was correct: flag it for review (still not stored)."""
    entry = get_entry(memory_id)
    if not entry or entry["status"] != "pending":
        return False
    meta = dict(entry["metadata"])
    meta.update({"user_verified": True, "feedback": "correct"})
    with _connect() as conn:
        conn.execute(
            "UPDATE lesson_queue SET metadata = ?, importance = MAX(importance, 9) WHERE id = ?",
            (json.dumps(meta), entry["id"]),
        )
    return True


def reject(memory_id: str, reason: str = "") -> bool:
    entry = get_entry(memory_id)
    if not entry or entry["status"] != "pending":
        return False
    with _connect() as conn:
        conn.execute(
            "UPDATE lesson_queue SET status = 'rejected', reviewed = ?, reason = ? WHERE id = ?",
            (time.time(), reason or None, entry["id"]),
        )
    return True


def approve(memory_id: str) -> str | None:
    """Store a pending lesson in the vector store. Returns the new memory id."""
    from SemanticMemory import add_memory  # late import: SemanticMemory imports this module

    entry = get_entry(memory_id)
    if not entry or entry["status"] != "pending":
        return None
    meta = dict(entry["metadata"])
    meta["reviewed"] = True
    mid = add_memory(
        entry["text"],
        importance_score=int(entry["importance"]),
        metadata=meta,
        collection=entry["collection"],
    )
    with _connect() as conn:
        conn.execute(
            "UPDATE lesson_queue SET status = 'approved', reviewed = ?, memory_id = ? WHERE id = ?",
            (time.time(), mid, entry["id"]),
        )
    return mid
