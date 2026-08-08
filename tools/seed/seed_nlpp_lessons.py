#!/usr/bin/env python3
"""Seed NLPP domain lessons into Chroma coding_lessons (P5). Idempotent by seed_id."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from blossom_seed.nlpp import DEFAULT_JSON, _seed_exists, seed_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed NLPP coding lessons (P5)")
    parser.add_argument("--json", default=str(DEFAULT_JSON))
    parser.add_argument(
        "--force",
        action="store_true",
        help="Insert even if seed_id already exists (creates duplicates)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List lessons without writing",
    )
    args = parser.parse_args(argv)

    path = Path(args.json)
    if not path.is_file():
        print(f"Missing {path}", file=sys.stderr)
        return 1

    if args.dry_run:
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            sid = row.get("seed_id")
            exists = _seed_exists(str(sid))
            print(f"{'skip' if exists else 'would insert'}: {sid}")
        return 0

    summary = seed_all(path, force=args.force)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
