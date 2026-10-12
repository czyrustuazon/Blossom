#!/usr/bin/env python3
"""Seed Chroma lessons from catalog groups, JSONL, packs, markdown, or rag dirs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from blossom_seed.catalog import DEFAULT_CATALOG, seed_catalog
from blossom_seed.chroma_lessons import (
    DEFAULT_JSONL,
    _is_product_catalog_row,
    _load_jsonl,
    dry_run,
    dry_run_md,
    dry_run_meta_jsonl,
    dry_run_pack,
    dry_run_product_jsonl,
    dry_run_rag_dir,
    seed_all,
    seed_md,
    seed_meta_jsonl,
    seed_pack,
    seed_product_jsonl,
    seed_rag_dir,
)


def _print_rows(rows: list[dict]) -> None:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed Chroma lessons (catalog groups, JSONL, pack, markdown, dir)"
    )
    parser.add_argument(
        "--catalog",
        nargs="?",
        const=str(DEFAULT_CATALOG),
        default=None,
        help=f"Apply tools/seed/catalog.json (default path: {DEFAULT_CATALOG})",
    )
    parser.add_argument(
        "--group",
        action="append",
        default=[],
        help="With --catalog: only these groups (repeatable), e.g. process ml-local",
    )
    parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help="With --catalog: only these scopes (general|product|nlpp)",
    )
    parser.add_argument(
        "--jsonl",
        default=None,
        help=f"Single JSONL file (default when no other mode: {DEFAULT_JSONL})",
    )
    parser.add_argument(
        "--pack",
        default=None,
        help="Pen-testing rag-seeds directory (chunks/ + qa/)",
    )
    parser.add_argument(
        "--dir",
        default=None,
        help="Product rag/ directory (SEED.md + qa_pairs.jsonl + optional JSONL)",
    )
    parser.add_argument(
        "--md",
        default=None,
        help="Markdown rag-seed file (## Document:/## DOC: or plain ## sections)",
    )
    parser.add_argument(
        "--product",
        default=None,
        help="Product/domain tag for --md/--dir/product JSONL (default: parent repo folder)",
    )
    parser.add_argument(
        "--domain",
        default=None,
        help="Domain tag for --md/--dir/product JSONL (default: same as --product)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Insert even if seed_id already exists (creates duplicates)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete prior seeds for each product/scope before insert",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List lessons / catalog plan without writing",
    )
    args = parser.parse_args(argv)

    if args.catalog is not None:
        summary = seed_catalog(
            Path(args.catalog) if args.catalog else DEFAULT_CATALOG,
            groups=args.group or None,
            scopes=args.scope or None,
            force=args.force,
            replace=args.replace,
            dry_run=args.dry_run,
        )
        print(json.dumps(summary, indent=2))
        return 1 if summary.get("errors") else 0

    modes = [bool(args.pack), bool(args.jsonl), bool(args.md), bool(args.dir)]
    if sum(modes) > 1:
        print("Use only one of --pack, --jsonl, --md, or --dir (or --catalog)", file=sys.stderr)
        return 2

    if args.dir:
        rag_dir = Path(args.dir)
        if not rag_dir.is_dir():
            print(f"Missing rag directory: {rag_dir}", file=sys.stderr)
            return 1
        if args.dry_run:
            _print_rows(dry_run_rag_dir(rag_dir, product=args.product, domain=args.domain))
            return 0
        summary = seed_rag_dir(
            rag_dir,
            product=args.product,
            domain=args.domain,
            force=args.force,
            replace=args.replace,
        )
        print(json.dumps(summary, indent=2))
        return 0

    if args.md:
        md = Path(args.md)
        if not md.is_file():
            print(f"Missing markdown seed: {md}", file=sys.stderr)
            return 1
        if args.dry_run:
            _print_rows(dry_run_md(md, product=args.product, domain=args.domain))
            return 0
        summary = seed_md(
            md,
            product=args.product,
            domain=args.domain,
            force=args.force,
            replace=args.replace,
        )
        print(json.dumps(summary, indent=2))
        return 0

    if args.pack:
        pack = Path(args.pack)
        if not pack.is_dir():
            print(f"Missing pack directory: {pack}", file=sys.stderr)
            return 1
        if args.dry_run:
            _print_rows(dry_run_pack(pack))
            return 0
        summary = seed_pack(pack, force=args.force, replace=args.replace)
        print(json.dumps(summary, indent=2))
        return 0

    path = Path(args.jsonl) if args.jsonl else DEFAULT_JSONL
    if not path.is_file():
        print(f"Missing {path}", file=sys.stderr)
        return 1

    use_product = False
    use_meta = False
    if args.jsonl:
        try:
            sample = _load_jsonl(path)
            if sample and _is_product_catalog_row(sample[0]):
                use_product = True
            elif sample and isinstance(sample[0].get("metadata"), dict):
                # Metadata JSONL from decomp rag_seeds (or similar packs).
                use_meta = True
        except Exception as exc:
            print(f"Failed to read {path}: {exc}", file=sys.stderr)
            return 1

    if use_product:
        if args.dry_run:
            _print_rows(
                dry_run_product_jsonl(path, product=args.product, domain=args.domain)
            )
            return 0
        summary = seed_product_jsonl(
            path,
            product=args.product,
            domain=args.domain,
            force=args.force,
            replace=args.replace,
        )
        print(json.dumps(summary, indent=2))
        return 0

    if use_meta:
        if args.dry_run:
            _print_rows(dry_run_meta_jsonl(path))
            return 0
        summary = seed_meta_jsonl(
            path,
            product=args.product,
            force=args.force or args.replace,
            replace=args.replace,
        )
        print(json.dumps(summary, indent=2))
        return 0

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
