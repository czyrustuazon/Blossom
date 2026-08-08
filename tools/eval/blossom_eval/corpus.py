from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CheckSpec:
    id: str
    type: str
    description: str = ""
    path: str = ""
    value: str = ""
    pattern: str = ""
    command: str = ""
    expect_exit: int = 0
    stdout_pattern: str = ""
    case_insensitive: bool = False


@dataclass
class TaskSpec:
    id: str
    title: str
    prompt: str
    domain: str
    tags: list[str]
    mode: str
    fixtures: dict[str, str]
    checks: list[CheckSpec]
    task_dir: Path

    @property
    def fixture_paths(self) -> dict[str, Path]:
        out: dict[str, Path] = {}
        for rel, fixture_ref in self.fixtures.items():
            out[rel.replace("\\", "/")] = (self.task_dir / fixture_ref).resolve()
        return out


@dataclass
class CorpusSpec:
    id: str
    title: str
    description: str
    domains: list[str]
    corpus_dir: Path
    tasks: list[TaskSpec] = field(default_factory=list)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _parse_check(raw: dict[str, Any]) -> CheckSpec:
    return CheckSpec(
        id=str(raw.get("id") or raw.get("type") or "check"),
        type=str(raw.get("type") or "contains"),
        description=str(raw.get("description") or ""),
        path=str(raw.get("path") or ""),
        value=str(raw.get("value") or raw.get("substring") or ""),
        pattern=str(raw.get("pattern") or raw.get("regex") or ""),
        command=str(raw.get("command") or raw.get("cmd") or ""),
        expect_exit=int(raw.get("expect_exit", raw.get("expectExit", 0))),
        stdout_pattern=str(raw.get("stdout_pattern") or raw.get("stdoutPattern") or ""),
        case_insensitive=bool(raw.get("case_insensitive", raw.get("caseInsensitive", False))),
    )


def _parse_task(task_dir: Path) -> TaskSpec:
    meta = _load_json(task_dir / "task.json")
    checks = [_parse_check(c) for c in meta.get("checks") or []]
    fixtures = {
        str(k).replace("\\", "/"): str(v)
        for k, v in (meta.get("fixtures") or {}).items()
    }
    return TaskSpec(
        id=str(meta["id"]),
        title=str(meta.get("title") or meta["id"]),
        prompt=str(meta["prompt"]),
        domain=str(meta.get("domain") or ""),
        tags=[str(t) for t in meta.get("tags") or []],
        mode=str(meta.get("mode") or "apply"),
        fixtures=fixtures,
        checks=checks,
        task_dir=task_dir,
    )


def load_corpus(corpus_dir: Path) -> CorpusSpec:
    corpus_dir = corpus_dir.resolve()
    meta_path = corpus_dir / "corpus.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"Missing corpus.json in {corpus_dir}")

    meta = _load_json(meta_path)
    tasks_root = corpus_dir / str(meta.get("tasks_dir") or "tasks")
    task_dirs = sorted(
        p for p in tasks_root.iterdir() if p.is_dir() and (p / "task.json").is_file()
    )
    tasks = [_parse_task(task_dir) for task_dir in task_dirs]
    if not tasks:
        raise ValueError(f"No tasks found under {tasks_root}")

    return CorpusSpec(
        id=str(meta["id"]),
        title=str(meta.get("title") or meta["id"]),
        description=str(meta.get("description") or ""),
        domains=[str(d) for d in meta.get("domains") or []],
        corpus_dir=corpus_dir,
        tasks=tasks,
    )


def build_user_prompt(task: TaskSpec, work_dir: Path) -> str:
    """Editor-style dump so ChatRouter routes to coding."""
    parts = ["[USER REQUEST]", task.prompt.strip(), ""]
    for rel, src in task.fixture_paths.items():
        if not src.is_file():
            raise FileNotFoundError(f"Fixture missing for {rel}: {src}")
        body = src.read_text(encoding="utf-8", errors="replace")
        parts.extend(
            [
                f'<<<FILE path="{rel}">>>',
                body.rstrip("\n"),
                "<<<END_FILE>>>",
                "",
            ]
        )
    parts.append(
        "Return updated files using fenced code blocks with path= labels "
        "(same paths as above). Include full file contents for each changed file."
    )
    return "\n".join(parts).strip()
