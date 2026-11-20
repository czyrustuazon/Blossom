from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent_loop import AgentRunLog, run_agent
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


_TEST_CMD_RE = re.compile(r"\b(pytest|unittest|node\s+--test|npm\s+(run\s+)?test)\b", re.I)
_CLAIM_RE = re.compile(r"\b(all\s+)?tests?\s+(now\s+)?(pass|passed|passing|green)\b", re.I)


def process_metrics(log: AgentRunLog) -> dict[str, Any]:
    """How Blossom worked, not just whether the result passed: the "reasoning" grade."""
    tools = log.transcript
    edit_names = {"search_replace", "write_file", "delete_file", "apply_fence"}
    edit_idx = [i for i, e in enumerate(tools) if e.name in edit_names and e.ok]
    read_idx = [i for i, e in enumerate(tools) if e.name in {"read_file", "search_text", "list_dir"} and e.ok]
    test_idx = [
        i for i, e in enumerate(tools)
        if e.name == "run_command" and _TEST_CMD_RE.search(str(e.args.get("command", "")))
    ]
    last_edit = edit_idx[-1] if edit_idx else -1
    tests_after = [i for i in test_idx if i > last_edit]
    verified = bool(tests_after) and tools[tests_after[-1]].ok
    return {
        "rounds": len(log.rounds),
        "elapsed_sec": log.elapsed_sec,
        "stop_reason": log.stop_reason,
        "edits": len(edit_idx),
        "files_touched": sorted(set(log.edits)),
        "researched_first": bool(read_idx) and (not edit_idx or read_idx[0] < edit_idx[0]),
        "ran_tests_after_last_edit": bool(tests_after),
        "verified_green": verified,
        "tool_failures": sum(1 for e in tools if not e.ok),
        "unverified_success_claim": bool(_CLAIM_RE.search(log.final_text or "")) and not verified,
    }


def _apply_reference(task: TaskSpec, work_dir: Path) -> None:
    """Overlay tasks/<id>/reference/ (a known-good solution) and apply its _delete.txt."""
    ref = task.task_dir / "reference"
    if not ref.is_dir():
        raise FileNotFoundError(f"No reference solution for {task.id}")
    for src in ref.rglob("*"):
        if src.is_file() and src.name != "_delete.txt":
            dest = work_dir / src.relative_to(ref)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    deletes = ref / "_delete.txt"
    if deletes.is_file():
        for rel in deletes.read_text(encoding="utf-8").split():
            (work_dir / rel).unlink(missing_ok=True)


def run_agent_task(
    task: TaskSpec,
    *,
    dry_run: bool = False,
    reference: bool = False,
    log_root: Path | None = None,
    keep_workdir: Path | None = None,
) -> TaskRunResult:
    work_dir_ctx = tempfile.TemporaryDirectory(prefix=f"blossom-agent-{task.id}-")
    work_dir = keep_workdir or Path(work_dir_ctx.name) / "ws"
    process: dict[str, Any] = {}
    final_text = ""
    try:
        project = task.project_path
        if not project or not project.is_dir():
            raise FileNotFoundError(f"project_dir missing for {task.id}")
        shutil.copytree(project, work_dir, dirs_exist_ok=True)
        if reference:
            _apply_reference(task, work_dir)
        elif not dry_run:
            log = run_agent(
                task.prompt, work_dir, max_rounds=task.max_rounds,
                log_dir=(log_root / task.id) if log_root else None,
                on_round=lambda n, msg: print(f"  [{task.id}] round {n}: {msg}", flush=True),
            )
            process = process_metrics(log)
            final_text = log.final_text
        hidden = task.hidden_path
        if hidden and hidden.is_dir():
            shutil.copytree(hidden, work_dir / "_acceptance", dirs_exist_ok=True)
        passed, checks = score_task(task, work_dir=work_dir, response_text=final_text)
        check_payload = [{"id": c.check_id, "passed": c.passed, "detail": c.detail} for c in checks]
        if process:
            check_payload.append({"id": "process", "passed": True, "detail": json.dumps(process)})
        return TaskRunResult(
            task_id=task.id, passed=passed, written_files=process.get("files_touched", []),
            check_results=check_payload, response_chars=len(final_text), error="",
            response_preview=final_text[:400].replace("\n", " "),
        )
    except Exception as exc:
        return TaskRunResult(task.id, False, [], [], len(final_text), str(exc), final_text[:400])
    finally:
        if keep_workdir is None:
            work_dir_ctx.cleanup()


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
    reference: bool = False,
    log_root: Path | None = None,
) -> list[TaskRunResult]:
    ok, detail = health_ok()
    if not dry_run and not reference and not ok:
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
        if task.mode == "agent":
            result = run_agent_task(task, dry_run=dry_run, reference=reference, log_root=log_root)
        else:
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
            notes="dry-run" if dry_run else ("reference" if reference else ""),
        )
    return results
