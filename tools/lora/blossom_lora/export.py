from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SCRIPT_DIR.parent
MIND_DB = PROJECT_ROOT / "Mind" / "CompanionMind.db"
DEFAULT_OUTPUT = PROJECT_ROOT / "Mind" / "lora_exports"

DEFAULT_SOURCE_PATTERNS = (
    "blossom_assistant_cursor",
    "blossom_assistant_gemini",
    "blossom_assistant_claude",
    "blossom_assistant_deescalate",
    "cursor_manual",
    "local_coder",
)


@dataclass
class TrainingExample:
    user_prompt: str
    answer: str
    source: str
    feedback_id: str


def _source_matches(source: str, patterns: Iterable[str]) -> bool:
    src = (source or "").lower()
    if not patterns:
        return True
    return any(p.lower() in src for p in patterns)


def fetch_correct_coding_turns(
    *,
    db_path: Path | None = None,
    source_patterns: Iterable[str] | None = None,
    min_answer_chars: int = 80,
    limit: int | None = None,
) -> list[TrainingExample]:
    db = db_path or MIND_DB
    if not db.is_file():
        raise FileNotFoundError(f"Mind database not found: {db}")

    patterns = tuple(source_patterns or DEFAULT_SOURCE_PATTERNS)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, user_prompt, answer, source
            FROM feedback_turns
            WHERE route='coding' AND verdict='correct'
            ORDER BY resolved_at DESC, created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    out: list[TrainingExample] = []
    for row in rows:
        prompt = (row["user_prompt"] or "").strip()
        answer = (row["answer"] or "").strip()
        source = (row["source"] or "").strip()
        if len(prompt) < 8 or len(answer) < min_answer_chars:
            continue
        if not _source_matches(source, patterns):
            continue
        out.append(
            TrainingExample(
                user_prompt=prompt,
                answer=answer,
                source=source,
                feedback_id=row["id"],
            )
        )
        if limit and len(out) >= limit:
            break
    return out


def load_format_habit_examples(rules_path: Path | None = None) -> list[TrainingExample]:
    """
    Synthetic pairs from coding_rules.txt — teaches PLAN → path= fences → Summary.
    Only for frozen output habits (not project facts).
    """
    path = rules_path or (PROJECT_ROOT / "PythonScripts" / "coding_rules.txt")
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []

    chunks = [c.strip() for c in re.split(r"\n{2,}", text) if c.strip()]
    examples: list[TrainingExample] = []
    for idx, chunk in enumerate(chunks[:12]):
        if len(chunk) < 40:
            continue
        examples.append(
            TrainingExample(
                user_prompt=(
                    "Apply Blossom coding protocol for a multi-file edit. "
                    f"Follow rule chunk {idx + 1}."
                ),
                answer=chunk[:6000],
                source="coding_rules_format_habit",
                feedback_id=f"synthetic-rules-{idx}",
            )
        )
    return examples


def to_sharegpt(examples: list[TrainingExample]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ex in examples:
        rows.append(
            {
                "conversations": [
                    {"from": "human", "value": ex.user_prompt},
                    {"from": "gpt", "value": ex.answer},
                ],
                "source": ex.source,
                "feedback_id": ex.feedback_id,
            }
        )
    return rows


def to_alpaca(examples: list[TrainingExample]) -> list[dict[str, Any]]:
    instruction = (
        "You are Blossom's local coding engine. Use path= fenced blocks for edits, "
        "respect CREATE vs EDIT, and end with a ### Summary when appropriate."
    )
    rows: list[dict[str, Any]] = []
    for ex in examples:
        rows.append(
            {
                "instruction": instruction,
                "input": ex.user_prompt,
                "output": ex.answer,
                "source": ex.source,
                "feedback_id": ex.feedback_id,
            }
        )
    return rows


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def export_dataset(
    *,
    output_dir: Path | None = None,
    include_rules_habits: bool = True,
    source_patterns: Iterable[str] | None = None,
    min_examples: int = 1,
) -> dict[str, Any]:
    feedback_examples = fetch_correct_coding_turns(source_patterns=source_patterns)
    rules_examples = load_format_habit_examples() if include_rules_habits else []
    combined = feedback_examples + rules_examples
    if len(combined) < min_examples:
        raise ValueError(
            f"Need at least {min_examples} training example(s); found {len(combined)} "
            f"({len(feedback_examples)} from 👍 feedback, {len(rules_examples)} from coding_rules)."
        )

    out_dir = output_dir or DEFAULT_OUTPUT
    out_dir.mkdir(parents=True, exist_ok=True)
    sharegpt_path = out_dir / "sharegpt.jsonl"
    alpaca_path = out_dir / "alpaca.jsonl"
    meta_path = out_dir / "export_meta.json"

    write_jsonl(to_sharegpt(combined), sharegpt_path)
    write_jsonl(to_alpaca(combined), alpaca_path)
    meta = {
        "feedback_examples": len(feedback_examples),
        "rules_habit_examples": len(rules_examples),
        "total": len(combined),
        "sharegpt": str(sharegpt_path),
        "alpaca": str(alpaca_path),
        "source_patterns": list(source_patterns or DEFAULT_SOURCE_PATTERNS),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta
