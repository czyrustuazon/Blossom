#!/usr/bin/env python3
"""Export 👍 coding turns (+ optional coding_rules habits) for LoRA training."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from blossom_lora.export import DEFAULT_OUTPUT, export_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export Blossom LoRA dataset (P6)")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Output directory (default: Mind/lora_exports)",
    )
    parser.add_argument(
        "--no-rules-habits",
        action="store_true",
        help="Skip synthetic pairs from coding_rules.txt",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Source substring filter (repeatable). Default: assistant/cursor sources.",
    )
    parser.add_argument(
        "--min-examples",
        type=int,
        default=1,
        help="Minimum rows required to export",
    )
    args = parser.parse_args(argv)

    try:
        meta = export_dataset(
            output_dir=Path(args.output),
            include_rules_habits=not args.no_rules_habits,
            source_patterns=args.source or None,
            min_examples=args.min_examples,
        )
    except ValueError as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
