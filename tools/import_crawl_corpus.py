#!/usr/bin/env python3
"""Embed the first-pass crawl snapshots into the Assistant Chroma store.

Reads Mind/rag/web_crawl/rag_docs.jsonl and rag_code.jsonl and upserts them
into crawl_docs and crawl_code, using each row's crawl id. The embedding
function is Chroma's default (same one SemanticMemory uses to query), so a
later query through _get_collection stays in the same vector space.

Safe to restart: progress is the number of lines already committed, in
Mind/rag/web_crawl/import_progress.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "PythonScripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import MindStores
import SemanticMemory
from MindStores import SURFACE_ASSISTANT, surface_scope

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "Mind" / "rag" / "web_crawl"
PROGRESS = CORPUS / "import_progress.json"
BATCH = 256

META_KEYS = (
    "url",
    "title",
    "section",
    "breadcrumb",
    "chunk_index",
    "source",
    "content_hash",
    "page_kind",
    "language",
    "canonical_url",
    "sample_index",
    "kind",
)


def _meta(row: dict) -> dict:
    raw = dict(row.get("metadata") or {})
    raw["kind"] = row.get("kind") or ""
    out: dict = {"source": "web_crawl"}
    for key in META_KEYS:
        value = raw.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            out[key] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = value
        else:
            out[key] = str(value)[:2000]
    return out


def _load_progress() -> dict[str, int]:
    if not PROGRESS.exists():
        return {}
    return json.loads(PROGRESS.read_text(encoding="utf-8"))


def _save_progress(progress: dict[str, int]) -> None:
    PROGRESS.write_text(json.dumps(progress), encoding="utf-8")


def import_file(path: Path, collection: str, *, skip: int) -> int:
    token = MindStores.set_surface(SURFACE_ASSISTANT)
    try:
        coll = SemanticMemory._get_collection(collection, surface=SURFACE_ASSISTANT)
    finally:
        MindStores._SURFACE.reset(token)
    if coll is None:
        raise RuntimeError(f"could not open collection {collection}")

    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []
    seen = 0
    written = 0
    started = time.perf_counter()

    def flush() -> None:
        nonlocal written
        if not ids:
            return
        coll.upsert(ids=ids, documents=docs, metadatas=metas)
        written += len(ids)
        ids.clear()
        docs.clear()
        metas.clear()

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            seen += 1
            if seen <= skip:
                continue
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            text = str(row.get("text") or "").strip()
            rid = str(row.get("id") or "").strip()
            if not text or not rid:
                continue
            ids.append(rid)
            docs.append(text)
            metas.append(_meta(row))
            if len(ids) >= BATCH:
                flush()
                done = skip + written
                elapsed = time.perf_counter() - started
                rate = written / elapsed if elapsed else 0
                print(
                    f"{collection}: committed {done} ({rate:.0f} rows/s)",
                    flush=True,
                )
                progress = _load_progress()
                progress[collection] = done
                _save_progress(progress)
        flush()
        progress = _load_progress()
        progress[collection] = skip + written
        _save_progress(progress)
    print(f"{collection}: done, upserted {written}, skipped {skip}", flush=True)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", type=Path, default=CORPUS / "rag_docs.jsonl")
    parser.add_argument("--code", type=Path, default=CORPUS / "rag_code.jsonl")
    args = parser.parse_args()
    progress = _load_progress()
    with surface_scope(SURFACE_ASSISTANT):
        import_file(
            args.docs,
            SemanticMemory.COLLECTION_CRAWL_DOCS,
            skip=int(progress.get(SemanticMemory.COLLECTION_CRAWL_DOCS) or 0),
        )
        import_file(
            args.code,
            SemanticMemory.COLLECTION_CRAWL_CODE,
            skip=int(progress.get(SemanticMemory.COLLECTION_CRAWL_CODE) or 0),
        )


if __name__ == "__main__":
    main()
