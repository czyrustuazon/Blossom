"""Seed Chroma lessons (NLPP JSONL or generic pen-testing rag-seeds packs)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = PROJECT_ROOT / "PythonScripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from SemanticMemory import (  # noqa: E402
    COLLECTION_CODING,
    COLLECTION_HARD_BANS,
    _get_collection,
    add_memory,
)

DEFAULT_JSONL = Path(__file__).resolve().parent.parent / "nlpp_chroma_lessons.jsonl"
SOURCE_NLPP = "seed_chroma_nlpp"
SOURCE_PENTEST = "seed_pen_testing"
PRODUCT_PENTEST = "pen-testing"
DOMAIN_PENTEST = "pen-testing"
# Older batches to purge when re-seeding under the generic name.
LEGACY_PENTEST_BATCHES = ("seed_trace_viper", SOURCE_PENTEST)
LEGACY_PENTEST_PRODUCTS = ("trace-viper", "traceviper", PRODUCT_PENTEST)
LEGACY_PENTEST_DOMAINS = ("traceviper", "trace-viper", DOMAIN_PENTEST)

SEVERITY_IMPORTANCE = {
    "critical": 10,
    "high": 9,
    "medium": 7,
    "low": 5,
}


def _seed_exists(seed_id: str, collection: str) -> bool:
    coll = _get_collection(collection)
    try:
        got = coll.get(where={"seed_id": seed_id}, include=[])
    except Exception:
        return False
    return bool(got.get("ids"))


def _target_collections(meta: dict[str, Any], kind: str) -> list[str]:
    explicit = str(meta.get("collection_target") or "").strip().lower()
    if explicit in {"hard_bans", "hard_ban", "bans"}:
        return [COLLECTION_HARD_BANS]
    if explicit in {"lessons", "coding", "coding_lessons"}:
        return [COLLECTION_CODING]
    if kind == "hard_ban":
        return [COLLECTION_HARD_BANS]
    return [COLLECTION_CODING]


def _importance(meta: dict[str, Any]) -> int:
    if "importance" in meta:
        try:
            return max(1, min(10, int(meta["importance"])))
        except (TypeError, ValueError):
            pass
    if meta.get("safety_critical") is True or str(meta.get("safety_critical")).lower() in {
        "true",
        "1",
        "yes",
    }:
        return 10
    severity = str(meta.get("severity") or "medium").lower()
    return SEVERITY_IMPORTANCE.get(severity, 7)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # utf-8-sig: some rag-seeds exports may carry a BOM
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON — {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_no}: each line must be a JSON object")
        rows.append(row)
    return rows


def _tags_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value)


def _is_pentest_meta(meta: dict[str, Any]) -> bool:
    product = str(meta.get("product") or "").lower()
    domain = str(meta.get("domain") or "").lower()
    batch = str(meta.get("seed_batch") or "").lower()
    return (
        product in LEGACY_PENTEST_PRODUCTS
        or domain in LEGACY_PENTEST_DOMAINS
        or batch in LEGACY_PENTEST_BATCHES
        or product == PRODUCT_PENTEST
        or domain == DOMAIN_PENTEST
    )


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map NLPP / pen-testing rag-seeds JSONL shapes onto a common seed row."""
    # Pack QA: {id, question, answer, tags, sources}
    if "question" in row and "answer" in row and "text" not in row and "document" not in row:
        tags = _tags_str(row.get("tags"))
        sources = row.get("sources") or []
        source = (
            ",".join(str(s) for s in sources)
            if isinstance(sources, list)
            else str(sources or SOURCE_PENTEST)
        )
        return {
            "id": str(row.get("id") or "").strip(),
            "text": (
                f"Symptom / ask: {str(row['question']).strip()}\n"
                f"Answer: {str(row['answer']).strip()}\n"
                f"Pointer: {source}"
            ),
            "metadata": {
                "domain": DOMAIN_PENTEST,
                "kind": "qa",
                "severity": "high",
                "source": source or SOURCE_PENTEST,
                "collection_target": "lessons",
                "tags": tags,
                "product": PRODUCT_PENTEST,
                "seed_batch": SOURCE_PENTEST,
            },
        }

    # Pack normalized_for_vectorstore: {id, document, metadata}
    if "document" in row and ("text" not in row or not row.get("text")):
        meta = dict(row.get("metadata") or {})
        tags = _tags_str(meta.get("tags"))
        safety = bool(meta.get("safety_critical", False))
        return {
            "id": str(row.get("id") or "").strip(),
            "text": str(row.get("document") or "").strip(),
            "metadata": {
                "domain": DOMAIN_PENTEST,
                "kind": "hard_ban" if safety else "verified",
                # Keep pen-testing safety in coding_lessons (not nlpp_hard_bans).
                "severity": "critical" if safety else "high",
                "source": str(meta.get("source_path") or SOURCE_PENTEST),
                "collection_target": "lessons",
                "tags": tags,
                "doc_id": str(meta.get("doc_id") or ""),
                "safety_critical": safety,
                "product": PRODUCT_PENTEST,
                "seed_batch": SOURCE_PENTEST,
                "importance": 10 if safety else 8,
            },
        }

    # Pack corpus.jsonl: {id, text, tags, source_path, safety_critical, ...}
    if "text" in row and ("metadata" not in row or not row.get("metadata")) and (
        row.get("doc_id") or row.get("source_path") or row.get("tags") is not None
    ):
        tags = _tags_str(row.get("tags"))
        safety = bool(row.get("safety_critical", False))
        source = str(row.get("source_path") or SOURCE_PENTEST)
        return {
            "id": str(row.get("id") or "").strip(),
            "text": str(row.get("text") or "").strip(),
            "metadata": {
                "domain": DOMAIN_PENTEST,
                "kind": "hard_ban" if safety else "verified",
                "severity": "critical" if safety else "high",
                "source": source,
                "collection_target": "lessons",
                "tags": tags,
                "doc_id": str(row.get("doc_id") or ""),
                "safety_critical": safety,
                "product": PRODUCT_PENTEST,
                "seed_batch": SOURCE_PENTEST,
                "importance": 10 if safety else 8,
            },
        }

    # NLPP / already-normalized Blossom shape
    meta = dict(row.get("metadata") or {})
    body = str(row.get("text") or row.get("answer") or row.get("document") or "").strip()
    return {
        "id": str(row.get("id") or row.get("seed_id") or "").strip(),
        "text": body,
        "metadata": meta,
    }


def _label_for(meta: dict[str, Any]) -> str:
    if _is_pentest_meta(meta):
        return "pen-testing"
    if meta.get("domain") or meta.get("seed_batch") == SOURCE_NLPP:
        return "NLPP"
    return "domain"


def delete_pentest_seeds(collection: str = COLLECTION_CODING) -> dict[str, Any]:
    """Remove prior pen-testing / legacy trace-viper seeded rows from a collection."""
    coll = _get_collection(collection)
    deleted_ids: list[str] = []
    try:
        got = coll.get(include=["metadatas"])
    except Exception as exc:
        return {"deleted": 0, "ids": [], "error": str(exc)}

    ids = got.get("ids") or []
    metas = got.get("metadatas") or []
    for mid, meta in zip(ids, metas):
        meta = meta or {}
        batch = str(meta.get("seed_batch") or "")
        product = str(meta.get("product") or "").lower()
        domain = str(meta.get("domain") or "").lower()
        if (
            batch in LEGACY_PENTEST_BATCHES
            or product in LEGACY_PENTEST_PRODUCTS
            or domain in LEGACY_PENTEST_DOMAINS
        ):
            deleted_ids.append(mid)

    if deleted_ids:
        # Chroma delete accepts batches; chunk to stay safe on large packs.
        chunk = 100
        for i in range(0, len(deleted_ids), chunk):
            coll.delete(ids=deleted_ids[i : i + chunk])
    return {"deleted": len(deleted_ids), "ids": deleted_ids, "collection": collection}


def _store_row(row: dict[str, Any], *, force: bool = False) -> list[tuple[str, str]]:
    """Returns list of (seed_id, collection) inserted."""
    normalized = normalize_row(row)
    seed_id = str(normalized.get("id") or "").strip()
    if not seed_id:
        raise ValueError("Lesson missing id")

    body = str(normalized.get("text") or "").strip()
    if not body:
        raise ValueError(f"{seed_id}: empty text")

    meta_in = dict(normalized.get("metadata") or {})
    kind = str(meta_in.get("kind") or "verified").strip() or "verified"
    # Never route pen-testing pack rows into NLPP hard-ban collection.
    if _is_pentest_meta(meta_in):
        targets = [COLLECTION_CODING]
    else:
        targets = _target_collections(meta_in, kind)
    importance = _importance(meta_in)

    topic = str(
        meta_in.get("topic")
        or meta_in.get("doc_id")
        or meta_in.get("domain")
        or kind
    )
    label = _label_for(meta_in)
    document = f"[{label} seed: {topic} | {seed_id}]\n{body[:4000]}"

    batch = str(meta_in.get("seed_batch") or SOURCE_NLPP)
    stored: list[tuple[str, str]] = []
    for collection in targets:
        if not force and _seed_exists(seed_id, collection):
            continue
        meta = {
            "source": str(meta_in.get("source") or batch),
            "kind": kind,
            "seed_id": seed_id,
            "domain": str(meta_in.get("domain") or ""),
            "severity": str(meta_in.get("severity") or ""),
            "seed_batch": batch,
            "product": str(meta_in.get("product") or ""),
        }
        if meta_in.get("tags"):
            meta["tags"] = str(meta_in["tags"])[:500]
        if meta_in.get("doc_id"):
            meta["doc_id"] = str(meta_in["doc_id"])
        if meta_in.get("safety_critical") is not None:
            meta["safety_critical"] = bool(meta_in["safety_critical"])
        if "pkg" in meta_in and meta_in["pkg"] is not None:
            try:
                meta["pkg"] = int(meta_in["pkg"])
            except (TypeError, ValueError):
                meta["pkg"] = str(meta_in["pkg"])

        add_memory(
            document,
            importance_score=importance,
            metadata=meta,
            collection=collection,
        )
        stored.append((seed_id, collection))
    return stored


def seed_all(
    jsonl_path: Path | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    path = jsonl_path or DEFAULT_JSONL
    rows = _load_jsonl(path)
    return _seed_rows(rows, force=force, source_label=str(path))


def seed_pack(
    pack_dir: Path,
    *,
    force: bool = False,
    replace: bool = False,
) -> dict[str, Any]:
    """Ingest a pen-testing rag-seeds directory.

    Prefers chunks/normalized_for_vectorstore.jsonl, else chunks/corpus.jsonl,
    plus qa/qa_pairs.jsonl when present.
    """
    root = Path(pack_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Pack directory not found: {root}")

    paths: list[Path] = []
    normalized = root / "chunks" / "normalized_for_vectorstore.jsonl"
    corpus = root / "chunks" / "corpus.jsonl"
    qa = root / "qa" / "qa_pairs.jsonl"

    if normalized.is_file():
        paths.append(normalized)
    elif corpus.is_file():
        paths.append(corpus)
    if qa.is_file():
        paths.append(qa)

    if not paths:
        raise FileNotFoundError(
            f"No ingestable JSONL under {root} "
            "(expected chunks/normalized_for_vectorstore.jsonl or chunks/corpus.jsonl)"
        )

    purged = None
    if replace:
        purged = delete_pentest_seeds(COLLECTION_CODING)

    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(_load_jsonl(path))

    summary = _seed_rows(rows, force=force, source_label=str(root))
    summary["files"] = [str(p) for p in paths]
    summary["product"] = PRODUCT_PENTEST
    summary["domain"] = DOMAIN_PENTEST
    if purged is not None:
        summary["purged"] = {"deleted": purged.get("deleted", 0)}
    return summary


def _seed_rows(
    rows: list[dict[str, Any]],
    *,
    force: bool = False,
    source_label: str = "",
) -> dict[str, Any]:
    inserted: list[dict[str, str]] = []
    skipped: list[str] = []
    for row in rows:
        normalized = normalize_row(row)
        seed_id = str(normalized.get("id") or "")
        stored = _store_row(normalized, force=force)
        if stored:
            for sid, coll in stored:
                inserted.append({"id": sid, "collection": coll})
        else:
            skipped.append(seed_id)

    return {
        "source": source_label,
        "inserted": inserted,
        "skipped": skipped,
        "total_rows": len(rows),
        "inserted_count": len(inserted),
        "skipped_count": len(skipped),
        "hard_bans_collection": COLLECTION_HARD_BANS,
        "lessons_collection": COLLECTION_CODING,
    }


def dry_run(jsonl_path: Path | None = None) -> list[dict[str, Any]]:
    path = jsonl_path or DEFAULT_JSONL
    return dry_run_rows(_load_jsonl(path))


def dry_run_pack(pack_dir: Path) -> list[dict[str, Any]]:
    root = Path(pack_dir)
    paths: list[Path] = []
    normalized = root / "chunks" / "normalized_for_vectorstore.jsonl"
    corpus = root / "chunks" / "corpus.jsonl"
    qa = root / "qa" / "qa_pairs.jsonl"
    if normalized.is_file():
        paths.append(normalized)
    elif corpus.is_file():
        paths.append(corpus)
    if qa.is_file():
        paths.append(qa)
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(_load_jsonl(path))
    return dry_run_rows(rows)


def dry_run_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    report = []
    for row in rows:
        normalized = normalize_row(row)
        seed_id = str(normalized.get("id") or "")
        meta = dict(normalized.get("metadata") or {})
        kind = str(meta.get("kind") or "verified")
        if _is_pentest_meta(meta):
            targets = [COLLECTION_CODING]
        else:
            targets = _target_collections(meta, kind)
        report.append(
            {
                "id": seed_id,
                "targets": targets,
                "exists": {c: _seed_exists(seed_id, c) for c in targets},
                "severity": meta.get("severity"),
                "domain": meta.get("domain"),
                "kind": kind,
                "product": meta.get("product"),
            }
        )
    return report
