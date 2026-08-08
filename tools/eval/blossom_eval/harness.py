from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .apply import apply_response_to_workdir
from .client import ask_coder, health_ok
from .corpus import CorpusSpec, TaskSpec, build_user_prompt, load_corpus
from .scorers import score_task
from .store import EvalStore


@dataclass
class TaskRunResult:
    task_id: str
    passed: bool
    written_files: list[str]
    check_results: list[dict[str, Any]]
    response_chars: int
    error: str
    response_preview: str


def _seed_workdir(task: TaskSpec, work_dir: Path) -> None:
    for rel, src in task.fixture_paths.items():
        if not src.is_file():
            raise FileNotFoundError(f"Fixture missing: {src}")
        dest = work_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def run_task(
    corpus: CorpusSpec,
    task: TaskSpec,
    *,
    dry_run: bool = False,
    keep_workdir: Path | None = None,
) -> TaskRunResult:
    work_dir_ctx = tempfile.TemporaryDirectory(prefix=f"blossom-eval-{task.id}-")
    work_dir = keep_workdir or Path(work_dir_ctx.name)
    response_text = ""
    written: list[str] = []
    error = ""

    try:
        if task.mode == "apply":
            _seed_workdir(task, work_dir)

        if dry_run:
            response_text = "[dry-run — model not called]"
        else:
            prompt = build_user_prompt(task, work_dir)
            response_text = ask_coder(prompt)
            if task.mode == "apply":
                written = apply_response_to_workdir(response_text, work_dir)

        passed, checks = score_task(task, work_dir=work_dir, response_text=response_text)
        check_payload = [
            {"id": c.check_id, "passed": c.passed, "detail": c.detail} for c in checks
        ]
        preview = response_text[:400].replace("\n", " ")
        return TaskRunResult(
            task_id=task.id,
            passed=passed,
            written_files=written,
            check_results=check_payload,
            response_chars=len(response_text),
            error=error,
            response_preview=preview,
        )
    except Exception as exc:
        return TaskRunResult(
            task_id=task.id,
            passed=False,
            written_files=written,
            check_results=[],
            response_chars=len(response_text),
            error=str(exc),
            response_preview=response_text[:400].replace("\n", " "),
        )
    finally:
        if keep_workdir is None:
            work_dir_ctx.cleanup()


def run_corpus(
    corpus_dir: Path,
    *,
    task_ids: list[str] | None = None,
    dry_run: bool = False,
    store: EvalStore | None = None,
) -> list[TaskRunResult]:
    ok, detail = health_ok()
    if not dry_run and not ok:
        raise RuntimeError(f"ChatRouter unreachable: {detail}")

    corpus = load_corpus(corpus_dir)
    selected = corpus.tasks
    if task_ids:
        wanted = set(task_ids)
        selected = [t for t in corpus.tasks if t.id in wanted]
        missing = wanted - {t.id for t in selected}
        if missing:
            raise ValueError(f"Unknown task id(s): {', '.join(sorted(missing))}")

    db = store or EvalStore()
    results: list[TaskRunResult] = []
    for task in selected:
        result = run_task(corpus, task, dry_run=dry_run)
        results.append(result)
        db.record(
            corpus_id=corpus.id,
            task_id=task.id,
            task_title=task.title,
            domain=task.domain or (corpus.domains[0] if corpus.domains else ""),
            mode=task.mode,
            passed=result.passed,
            written_files=result.written_files,
            check_results=result.check_results,
            response_chars=result.response_chars,
            error=result.error,
            notes="dry-run" if dry_run else "",
        )
    return results
