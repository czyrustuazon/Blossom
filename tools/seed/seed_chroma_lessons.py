#!/usr/bin/env python3
"""Seed Chroma lessons from NLPP JSONL or a pen-testing rag-seeds pack."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from blossom_seed.chroma_lessons import (
    DEFAULT_JSONL,
    dry_run,
    dry_run_pack,
    seed_all,
    seed_pack,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed hard bans + coding lessons into Chroma (JSONL or rag-seeds pack)"
    )
    parser.add_argument(
        "--jsonl",
        default=None,
        help=f"Single JSONL file (default when no --pack: {DEFAULT_JSONL})",
    )
    parser.add_argument(
        "--pack",
        default=None,
        help="Pen-testing rag-seeds directory (chunks/ + qa/)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Insert even if seed_id already exists (creates duplicates)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="With --pack: delete prior pen-testing / legacy trace-viper seeds first",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List lessons and whether seed_id already exists",
    )
    args = parser.parse_args(argv)

    if args.pack and args.jsonl:
        print("Use either --pack or --jsonl, not both", file=sys.stderr)
        return 2

    if args.pack:
        pack = Path(args.pack)
        if not pack.is_dir():
            print(f"Missing pack directory: {pack}", file=sys.stderr)
            return 1
        if args.dry_run:
            rows = dry_run_pack(pack)
            for row in rows:
                flags = [
                    f"{'skip' if exists else 'insert'}:{coll}"
                    for coll, exists in (row.get("exists") or {}).items()
                ]
                print(
                    f"{row['id']}\t{row.get('product')}\t{row.get('severity')}\t"
                    f"{row.get('domain')}\t{row.get('kind')}\t{','.join(flags)}"
                )
            print(f"# total {len(rows)}", file=sys.stderr)
            return 0
        summary = seed_pack(pack, force=args.force, replace=args.replace)
        print(json.dumps(summary, indent=2))
        return 0

    path = Path(args.jsonl) if args.jsonl else DEFAULT_JSONL
    if not path.is_file():
        print(f"Missing {path}", file=sys.stderr)
        return 1

    if args.dry_run:
        for row in dry_run(path):
            flags = [
                f"{'skip' if exists else 'insert'}:{coll}"
                for coll, exists in (row.get("exists") or {}).items()
            ]
            print(
                f"{row['id']}\t{row.get('severity')}\t{row.get('domain')}\t"
                f"{row.get('kind')}\t{','.join(flags)}"
            )
        return 0

    summary = seed_all(path, force=args.force)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
