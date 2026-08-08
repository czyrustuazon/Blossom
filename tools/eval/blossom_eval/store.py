from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_db_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    return root / "Mind" / "eval_results.db"


@dataclass
class RunRecord:
    run_id: int
    corpus_id: str
    task_id: str
    passed: bool
    mode: str
    written_files: list[str]
    check_results: list[dict[str, Any]]
    response_chars: int
    error: str
    created_at: str


class EvalStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = (db_path or default_db_path()).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS eval_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    corpus_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    task_title TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    written_files TEXT NOT NULL,
                    check_results TEXT NOT NULL,
                    response_chars INTEGER NOT NULL,
                    error TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_eval_runs_corpus
                    ON eval_runs(corpus_id, created_at);
                """
            )

    def record(
        self,
        *,
        corpus_id: str,
        task_id: str,
        task_title: str,
        domain: str,
        mode: str,
        passed: bool,
        written_files: list[str],
        check_results: list[dict[str, Any]],
        response_chars: int,
        error: str = "",
        notes: str = "",
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO eval_runs (
                    created_at, corpus_id, task_id, task_title, domain, mode,
                    passed, written_files, check_results, response_chars, error, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _utc_now(),
                    corpus_id,
                    task_id,
                    task_title,
                    domain,
                    mode,
                    1 if passed else 0,
                    json.dumps(written_files),
                    json.dumps(check_results),
                    response_chars,
                    error,
                    notes,
                ),
            )
            return int(cur.lastrowid)

    def summary(self, corpus_id: str | None = None, limit: int = 500) -> list[sqlite3.Row]:
        with self._connect() as conn:
            if corpus_id:
                return conn.execute(
                    """
                    SELECT * FROM eval_runs
                    WHERE corpus_id=?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (corpus_id, limit),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM eval_runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def pass_rate(self, corpus_id: str | None = None) -> tuple[int, int, float]:
        with self._connect() as conn:
            if corpus_id:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN passed=1 THEN 1 ELSE 0 END) AS passed
                    FROM eval_runs WHERE corpus_id=?
                    """,
                    (corpus_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN passed=1 THEN 1 ELSE 0 END) AS passed
                    FROM eval_runs
                    """
                ).fetchone()
        total = int(row["total"] or 0)
        passed = int(row["passed"] or 0)
        rate = (passed / total) if total else 0.0
        return total, passed, rate
