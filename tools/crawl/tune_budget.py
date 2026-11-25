"""Pick the cAST budget: share of stamped parts that fit the embedder's token window.

Samples rows from seek points across a crawl JSONL, chunks them at several budgets, and counts
tokens with the embedder's own tokenizer (Chroma's default all-MiniLM-L6-v2, 256-token window).

  python tools/crawl/tune_budget.py --file <rag_github.jsonl> --rows 3000
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cast_chunk import chunk_text, stamp  # noqa: E402


def load_tokenizer():
    from tokenizers import Tokenizer

    candidates = [
        Path.home() / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2" / "onnx" / "tokenizer.json",
    ]
    for c in candidates:
        if c.is_file():
            tok = Tokenizer.from_file(str(c))
            tok.no_truncation()
            return tok
    raise SystemExit("MiniLM tokenizer.json not found under ~/.cache/chroma (query Chroma once first)")


def sample_rows(path: Path, n: int, seeks: int = 60) -> list[dict]:
    size = path.stat().st_size
    per = max(1, n // seeks)
    rows: list[dict] = []
    with path.open("rb") as h:
        for i in range(seeks):
            h.seek(int(size * i / seeks))
            h.readline()
            for _ in range(per):
                line = h.readline()
                if not line:
                    break
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, required=True)
    ap.add_argument("--rows", type=int, default=3000)
    ap.add_argument("--budgets", default="500,600,700,800,900")
    args = ap.parse_args()
    tok = load_tokenizer()
    rows = [r for r in sample_rows(args.file, args.rows) if r.get("action", "upsert") != "delete" and r.get("text")]
    print(f"{len(rows)} rows sampled from {args.file.name}")
    for budget in [int(b) for b in args.budgets.split(",")]:
        t0 = time.perf_counter()
        counts, parts_per_row, chars, methods = [], [], [], {}
        for r in rows:
            meta = r.get("metadata") or {}
            parts, method = chunk_text(
                r["text"], language=meta.get("language"), path=meta.get("path"), kind=r.get("kind", ""), budget=budget
            )
            methods[method] = methods.get(method, 0) + 1
            parts_per_row.append(len(parts))
            where = f"{meta.get('repo', '')}/{meta.get('path', '')}".strip("/") or meta.get("url", "")
            for p in parts:
                text = stamp(p, where=where, language=str(meta.get("language") or ""))
                counts.append(len(tok.encode(text).ids))
                chars.append(len(text))
        dt = time.perf_counter() - t0
        fit = sum(c <= 256 for c in counts) / len(counts)
        print(
            f"budget {budget}: parts {len(counts)} ({statistics.mean(parts_per_row):.2f}/row), "
            f"fit<=256 tok {fit:.1%}, median {statistics.median(counts)} tok / {statistics.median(chars)} chars, "
            f"p90 {sorted(counts)[int(len(counts) * 0.9)]} tok, {len(rows) / dt:.0f} rows/s, methods {methods}"
        )


if __name__ == "__main__":
    main()
