#!/usr/bin/env python3
"""Run Blossom coding eval corpora (P4)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from blossom_eval.harness import run_corpus
from blossom_eval.store import EvalStore


def _default_corpora_root() -> Path:
    return Path(__file__).resolve().parent / "corpora"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Blossom eval corpora against ChatRouter. "
            "Corpus-agnostic — PHP, C#, assembly/RE, etc."
        )
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run one corpus or task")
    run_p.add_argument(
        "--corpus",
        required=True,
        help="Path to corpus folder (contains corpus.json + tasks/)",
    )
    run_p.add_argument("--task", action="append", default=[], help="Task id (repeatable)")
    run_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Seed fixtures and run checks only; do not call ChatRouter",
    )
    run_p.add_argument("--db", help="SQLite results path (default: Mind/eval_results.db)")

    report_p = sub.add_parser("report", help="Show pass rate from eval DB")
    report_p.add_argument("--corpus", help="Filter by corpus id")
    report_p.add_argument("--db", help="SQLite results path")
    report_p.add_argument("--limit", type=int, default=20, help="Recent rows to print")

    list_p = sub.add_parser("list", help="List bundled corpora")
    list_p.add_argument(
        "--root",
        default=str(_default_corpora_root()),
        help="Corpora root directory",
    )

    args = parser.parse_args(argv)
    store = EvalStore(Path(args.db)) if getattr(args, "db", None) else EvalStore()

    if args.cmd == "list":
        root = Path(args.root)
        if not root.is_dir():
            print(f"No corpora root: {root}", file=sys.stderr)
            return 1
        for corpus_dir in sorted(root.iterdir()):
            if not (corpus_dir / "corpus.json").is_file():
                continue
            print(corpus_dir.name)
        return 0

    if args.cmd == "report":
        rows = store.summary(getattr(args, "corpus", None), limit=args.limit)
        total, passed, rate = store.pass_rate(getattr(args, "corpus", None))
        print(f"Total runs: {total}  Passed: {passed}  Rate: {rate:.1%}")
        for row in rows:
            status = "PASS" if row["passed"] else "FAIL"
            print(
                f"[{row['id']}] {status} {row['corpus_id']}/{row['task_id']} "
                f"({row['created_at']})"
            )
            if row["error"]:
                print(f"  error: {row['error']}")
        return 0

    if args.cmd == "run":
        corpus_dir = Path(args.corpus)
        if not corpus_dir.is_dir():
            alt = _default_corpora_root() / args.corpus
            if alt.is_dir():
                corpus_dir = alt
        task_ids = args.task or None
        results = run_corpus(
            corpus_dir,
            task_ids=task_ids,
            dry_run=args.dry_run,
            store=store,
        )
        passed = sum(1 for r in results if r.passed)
        print(f"Finished {len(results)} task(s): {passed} passed, {len(results) - passed} failed")
        for result in results:
            mark = "PASS" if result.passed else "FAIL"
            print(f"\n{mark} {result.task_id}")
            if result.error:
                print(f"  error: {result.error}")
            if result.written_files:
                print(f"  written: {', '.join(result.written_files)}")
            for check in result.check_results:
                cmark = "ok" if check["passed"] else "x"
                print(f"  [{cmark}] {check['id']}: {check['detail']}")
        return 0 if passed == len(results) else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
