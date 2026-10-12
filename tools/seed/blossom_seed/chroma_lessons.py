"""Seed Chroma lessons (NLPP JSONL, rag-seeds packs, or markdown rag-seed docs)."""

from __future__ import annotations

import json
import re
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

from .catalog import family_for_product, group_for_category, stamp_taxonomy  # noqa: E402

DEFAULT_JSONL = Path(__file__).resolve().parent.parent / "nlpp" / "chroma_lessons.jsonl"
SOURCE_NLPP = "seed_chroma_nlpp"
SOURCE_PENTEST = "seed_pen_testing"
PRODUCT_PENTEST = "pen-testing"
DOMAIN_PENTEST = "pen-testing"
# Older batches to purge when re-seeding under the generic name.
LEGACY_PENTEST_BATCHES = ("seed_trace_viper", SOURCE_PENTEST)
LEGACY_PENTEST_PRODUCTS = ("trace-viper", "traceviper", PRODUCT_PENTEST)
LEGACY_PENTEST_DOMAINS = ("traceviper", "trace-viper", DOMAIN_PENTEST)
MD_BODY_MAX_CHARS = 3500
_QA_SECTION_TITLES = {
    "q&a training pairs",
    "qa training pairs",
    "q and a training pairs",
}

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


def _is_product_catalog_row(row: dict[str, Any]) -> bool:
    """Instagram Model AI–style rows: {id, category, title, source, tags, text}."""
    if not isinstance(row, dict):
        return False
    if row.get("metadata"):
        return False
    return bool(
        str(row.get("text") or "").strip()
        and row.get("title") is not None
        and row.get("category") is not None
    )


def normalize_product_catalog_row(
    row: dict[str, Any],
    *,
    product: str,
    domain: str,
    batch: str,
) -> dict[str, Any]:
    tags = _tags_str(row.get("tags"))
    title = str(row.get("title") or "").strip()
    category = str(row.get("category") or "product").strip().lower() or "product"
    body = str(row.get("text") or "").strip()
    source = str(row.get("source") or batch)
    raw_id = str(row.get("id") or "").strip()
    product_slug = _slug(product)
    if not raw_id:
        raw_id = _slug(title) or "row"
    seed_id = (
        raw_id
        if raw_id.startswith(f"{product_slug}-") or raw_id.startswith(product_slug)
        else f"{product_slug}-{raw_id}"
    )

    is_hard = category in {
        "policy",
        "hard_ban",
        "hard_bans",
        "anti_pattern",
        "anti-patterns",
    } or "anti-pattern" in title.lower()
    severity = "critical" if is_hard else "high"
    kind = "hard_ban" if is_hard else "verified"
    text = f"# {title}\n\n{body}".strip() if title else body

    scope = "general" if product_slug == "general" else "product"
    group = (
        group_for_category(category, default="process")
        if scope == "general"
        else "product-manual"
    )
    return {
        "id": seed_id,
        "text": text,
        "metadata": stamp_taxonomy(
            {
                "domain": domain if scope != "general" else category,
                "kind": kind,
                "severity": severity,
                "source": source,
                "collection_target": "lessons",
                "tags": tags,
                "product": product_slug,
                "seed_batch": batch,
                "doc_id": category,
                "topic": title or category,
                "importance": 10 if is_hard else 8,
            },
            scope=scope,
            group=group,
            family=family_for_product(product_slug),
            product=product_slug,
        ),
    }


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map NLPP / pen-testing / product-catalog JSONL shapes onto a common seed row."""
    # Already stamped product-catalog / Blossom rows with metadata.product
    meta_early = dict(row.get("metadata") or {})
    if meta_early.get("product") and (
        row.get("text") or row.get("document") or row.get("answer")
    ):
        body = str(row.get("text") or row.get("answer") or row.get("document") or "").strip()
        return {
            "id": str(row.get("id") or row.get("seed_id") or "").strip(),
            "text": body,
            "metadata": meta_early,
        }

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

    # Product catalog JSONL (before loose pen-testing corpus match)
    if _is_product_catalog_row(row):
        # Product must be stamped by seed_product_jsonl; fall back to id prefix only.
        product = str(row.get("product") or "product")
        domain = str(row.get("domain") or product)
        batch = str(row.get("seed_batch") or _product_batch(product))
        return normalize_product_catalog_row(
            row, product=product, domain=domain, batch=batch
        )

    # Pack corpus.jsonl: {id, text, source_path/doc_id/safety_critical, ...}
    # Require pen-testing markers — bare tags+text is not enough (product catalogs).
    if "text" in row and ("metadata" not in row or not row.get("metadata")) and (
        row.get("source_path") is not None
        or row.get("doc_id") is not None
        or "safety_critical" in row
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
    product = str(meta.get("product") or "").strip()
    if product:
        return product
    if meta.get("domain") or meta.get("seed_batch") == SOURCE_NLPP:
        return "NLPP"
    return "domain"


def _slug(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:max_len].strip("-") or "chunk")


def _product_batch(product: str) -> str:
    return f"seed_{_slug(product).replace('-', '_')}"


_SKIP_PRODUCT_DIRS = {
    "docs",
    "doc",
    "rag",
    "rag-seed",
    "rag-seeds",
    "rag_seeds",
    "seed",
    "seeds",
    "llm_train",
    "llm-train",
    "data",
    "corpus",
}


def _infer_product(path: Path, explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return _slug(explicit.strip())
    # Prefer repo folder name: .../anime-db-stream/docs/rag-seed.md
    # or .../Waifu Redraw/rag/seed.md
    for parent in Path(path).resolve().parents:
        name = parent.name.strip().lower()
        if name and name not in _SKIP_PRODUCT_DIRS:
            return _slug(name)
    return _slug(Path(path).stem)


def _split_md_subsections(title: str, body: str) -> list[tuple[str, str]]:
    """Keep whole Document sections when small; else split on ### headings."""
    body = (body or "").strip()
    if not body:
        return []
    if len(body) <= MD_BODY_MAX_CHARS:
        return [(title, body)]

    parts = re.split(r"(?m)^###\s+", body)
    chunks: list[tuple[str, str]] = []
    intro = (parts[0] or "").strip()
    if intro:
        chunks.append((title, intro))
    for part in parts[1:]:
        lines = part.splitlines()
        if not lines:
            continue
        sub = lines[0].strip()
        sub_body = "\n".join(lines[1:]).strip()
        if not sub_body:
            continue
        chunks.append((f"{title} / {sub}", sub_body))

    if len(chunks) <= 1 and len(body) > MD_BODY_MAX_CHARS:
        # Hard wrap oversized sections with no ### markers.
        hard: list[tuple[str, str]] = []
        step = MD_BODY_MAX_CHARS
        for i in range(0, len(body), step):
            piece = body[i : i + step].strip()
            if piece:
                hard.append((f"{title} (part {len(hard) + 1})", piece))
        return hard
    return chunks


def _parse_qa_md_section(
    body: str,
    *,
    product: str,
    domain: str,
    batch: str,
    source: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    parts = re.split(r"(?m)^### Q:\s*", body)
    for part in parts[1:]:
        match = re.match(r"(.*?)\n+A:\s*(.*)", part, flags=re.DOTALL)
        if not match:
            continue
        question = match.group(1).strip()
        answer = match.group(2).strip()
        # Stop before a trailing glossary-style table if one leaked in.
        answer = re.split(r"(?m)^##\s+", answer, maxsplit=1)[0].strip()
        if not question or not answer:
            continue
        seed_id = f"{_slug(product)}-qa-{_slug(question)}"
        rows.append(
            {
                "id": seed_id,
                "text": (
                    f"Symptom / ask: {question}\n"
                    f"Answer: {answer}\n"
                    f"Pointer: {source}"
                ),
                "metadata": {
                    "domain": domain,
                    "kind": "qa",
                    "severity": "high",
                    "source": source,
                    "collection_target": "lessons",
                    "product": product,
                    "seed_batch": batch,
                    "doc_id": "qa",
                    "importance": 8,
                },
            }
        )
    return rows


def _clean_md_section_title(title: str) -> str:
    cleaned = re.sub(r"^(?:DOC|Document):\s*", "", (title or "").strip(), flags=re.I)
    return cleaned.strip() or (title or "").strip()


def _iter_md_sections(text: str) -> list[tuple[str, str]]:
    """Yield (title, body) for ## Document:/## DOC: sections, else plain ## H2."""
    for pattern in (r"(?m)^## Document:\s*", r"(?m)^## DOC:\s*"):
        doc_parts = re.split(pattern, text)
        if len(doc_parts) > 1:
            sections: list[tuple[str, str]] = []
            for part in doc_parts[1:]:
                lines = part.splitlines()
                if not lines:
                    continue
                title = _clean_md_section_title(lines[0])
                body = "\n".join(lines[1:]).strip()
                body = re.sub(r"(?m)^\s*---\s*$", "", body).strip()
                if title:
                    sections.append((title, body))
            return sections

    # Plain ## section corpus (e.g. Waifu Redraw rag/seed.md)
    h2_parts = re.split(r"(?m)^##\s+", text)
    sections = []
    for part in h2_parts[1:]:
        lines = part.splitlines()
        if not lines:
            continue
        title = _clean_md_section_title(lines[0])
        body = "\n".join(lines[1:]).strip()
        # Drop horizontal-rule separators that trail section bodies.
        body = re.sub(r"(?m)^\s*---\s*$", "", body).strip()
        if title:
            sections.append((title, body))
    return sections


def normalize_product_qa_row(
    row: dict[str, Any],
    *,
    product: str,
    domain: str,
    batch: str,
    source: str = "",
) -> dict[str, Any]:
    question = str(row.get("question") or "").strip()
    answer = str(row.get("answer") or "").strip()
    tags = _tags_str(row.get("tags"))
    product_slug = _slug(product)
    raw_id = str(row.get("id") or "").strip()
    if raw_id:
        seed_id = (
            raw_id
            if raw_id.startswith(f"{product_slug}-") or raw_id.startswith(product_slug)
            else f"{product_slug}-qa-{raw_id}"
        )
    else:
        seed_id = f"{product_slug}-qa-{_slug(question)}"
    pointer = source or str(row.get("source") or batch)
    return {
        "id": seed_id,
        "text": (
            f"Symptom / ask: {question}\n"
            f"Answer: {answer}\n"
            f"Pointer: {pointer}"
        ),
        "metadata": {
            "domain": domain,
            "kind": "qa",
            "severity": "high",
            "source": pointer,
            "collection_target": "lessons",
            "tags": tags,
            "product": product_slug,
            "seed_batch": batch,
            "doc_id": "qa",
            "importance": 8,
        },
    }


def _is_prechunked_jsonl_row(row: dict[str, Any]) -> bool:
    """{id, text, metadata:{...}} rows (e.g. anime-db-tracker corpus.jsonl)."""
    if not isinstance(row, dict):
        return False
    if not str(row.get("text") or "").strip():
        return False
    meta = row.get("metadata")
    return isinstance(meta, dict) and bool(meta)


def normalize_prechunked_jsonl_row(
    row: dict[str, Any],
    *,
    product: str,
    domain: str,
    batch: str,
) -> dict[str, Any]:
    meta_in = dict(row.get("metadata") or {})
    product_slug = _slug(str(meta_in.get("project") or product))
    domain_name = _slug(str(meta_in.get("domain") or domain or product_slug))
    raw_id = str(row.get("id") or meta_in.get("topic") or "").strip() or "chunk"
    seed_id = (
        raw_id
        if raw_id.startswith(f"{product_slug}-") or raw_id.startswith(product_slug)
        else f"{product_slug}-{raw_id}"
    )
    tags = _tags_str(meta_in.get("tags"))
    source = str(meta_in.get("source") or batch)
    topic = str(meta_in.get("topic") or raw_id)
    body = str(row.get("text") or "").strip()
    return {
        "id": seed_id,
        "text": body,
        "metadata": {
            "domain": domain_name,
            "kind": "verified",
            "severity": "high",
            "source": source,
            "collection_target": "lessons",
            "tags": tags,
            "product": product_slug,
            "seed_batch": batch,
            "doc_id": topic,
            "topic": topic,
            "importance": 8,
        },
    }


def _load_train_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        for key in ("items", "data", "pairs", "examples"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            raise ValueError(f"{path}: expected a JSON array of QA pairs")
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array of QA pairs")
    return [row for row in data if isinstance(row, dict)]


def _discover_rag_dir_files(root: Path) -> dict[str, list[Path]]:
    """Find markdown seeds + QA/product/prechunked JSON under a product rag folder."""
    root = Path(root)
    md_names = ("SEED.md", "seed.md", "rag-seed.md", "rag_seed.md")
    md_files: list[Path] = []
    for name in md_names:
        candidate = root / name
        if candidate.is_file():
            md_files.append(candidate)
            break

    prechunked_files: list[Path] = []
    corpus_jsonl = root / "corpus.jsonl"
    if corpus_jsonl.is_file():
        try:
            sample = _load_jsonl(corpus_jsonl)
        except Exception:
            sample = []
        if sample and _is_prechunked_jsonl_row(sample[0]):
            prechunked_files.append(corpus_jsonl)

    # Prefer pre-chunked JSONL over raw corpus/*.md to avoid duplicates.
    if not prechunked_files and not md_files:
        md_files = sorted(root.glob("*.md"))
        # Skip pack README; only ingest topic markdown.
        md_files = [p for p in md_files if p.name.lower() != "readme.md"]
        corpus_dir = root / "corpus"
        if corpus_dir.is_dir():
            md_files.extend(sorted(corpus_dir.glob("*.md")))

    qa_files: list[Path] = []
    for candidate in (root / "qa_pairs.jsonl", root / "qa" / "qa_pairs.jsonl"):
        if candidate.is_file():
            qa_files.append(candidate)
            break

    train_files: list[Path] = []
    train_json = root / "train.json"
    if train_json.is_file():
        train_files.append(train_json)

    catalog_files: list[Path] = []
    for path in sorted(root.glob("*.jsonl")):
        if path in qa_files or path in prechunked_files:
            continue
        try:
            sample = _load_jsonl(path)
        except Exception:
            continue
        if sample and _is_product_catalog_row(sample[0]):
            catalog_files.append(path)

    return {
        "md": md_files,
        "qa": qa_files,
        "train": train_files,
        "prechunked": prechunked_files,
        "catalog": catalog_files,
    }


def load_rag_dir(
    rag_dir: Path,
    *,
    product: str | None = None,
    domain: str | None = None,
) -> tuple[list[dict[str, Any]], str, str, list[str]]:
    """Load a product rag directory into stamped seed rows."""
    root = Path(rag_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"RAG directory not found: {root}")

    product_name = _infer_product(root, product)
    domain_name = _slug(domain) if domain else product_name
    batch = _product_batch(product_name)
    discovered = _discover_rag_dir_files(root)
    files = (
        discovered["md"]
        + discovered["qa"]
        + discovered["train"]
        + discovered["prechunked"]
        + discovered["catalog"]
    )
    if not files:
        raise FileNotFoundError(
            f"No seed.md / corpus.jsonl / train.json / qa_pairs.jsonl under {root}"
        )

    rows: list[dict[str, Any]] = []
    for md_path in discovered["md"]:
        rows.extend(parse_rag_seed_md(md_path, product=product_name, domain=domain_name))

    for pre_path in discovered["prechunked"]:
        for raw in _load_jsonl(pre_path):
            if not _is_prechunked_jsonl_row(raw):
                continue
            rows.append(
                normalize_prechunked_jsonl_row(
                    raw, product=product_name, domain=domain_name, batch=batch
                )
            )

    for qa_path in discovered["qa"]:
        for raw in _load_jsonl(qa_path):
            if not (raw.get("question") and raw.get("answer")):
                continue
            rows.append(
                normalize_product_qa_row(
                    raw,
                    product=product_name,
                    domain=domain_name,
                    batch=batch,
                    source=str(qa_path.resolve()),
                )
            )

    for train_path in discovered["train"]:
        for raw in _load_train_json(train_path):
            if not (raw.get("question") and raw.get("answer")):
                continue
            contexts = raw.get("contexts") or []
            context_names = []
            if isinstance(contexts, list):
                for ctx in contexts:
                    if isinstance(ctx, dict) and ctx.get("filename"):
                        context_names.append(str(ctx["filename"]))
                    elif isinstance(ctx, str):
                        context_names.append(ctx)
            pointer = (
                ",".join(context_names)
                if context_names
                else str(train_path.resolve())
            )
            rows.append(
                normalize_product_qa_row(
                    raw,
                    product=product_name,
                    domain=domain_name,
                    batch=batch,
                    source=pointer,
                )
            )

    for catalog_path in discovered["catalog"]:
        catalog_rows, _, _ = load_product_jsonl(
            catalog_path, product=product_name, domain=domain_name
        )
        rows.extend(catalog_rows)

    return rows, product_name, domain_name, [str(p.resolve()) for p in files]


def parse_rag_seed_md(
    path: Path,
    *,
    product: str | None = None,
    domain: str | None = None,
) -> list[dict[str, Any]]:
    """Parse a markdown corpus (## Document: or plain ##) into seed rows."""
    md_path = Path(path)
    if not md_path.is_file():
        raise FileNotFoundError(f"Markdown seed not found: {md_path}")

    product_name = _infer_product(md_path, product)
    domain_name = _slug(domain) if domain else product_name
    batch = _product_batch(product_name)
    source = str(md_path.resolve())
    text = md_path.read_text(encoding="utf-8-sig")

    rows: list[dict[str, Any]] = []
    for title, body in _iter_md_sections(text):
        if title.lower() in _QA_SECTION_TITLES:
            rows.extend(
                _parse_qa_md_section(
                    body,
                    product=product_name,
                    domain=domain_name,
                    batch=batch,
                    source=source,
                )
            )
            continue

        # Hard-rule sections get higher importance (still coding_lessons only).
        is_hard = "hard rule" in title.lower() or "anti-pattern" in title.lower()
        severity = "critical" if is_hard else "high"
        importance = 10 if is_hard else 8
        kind = "hard_ban" if is_hard else "verified"

        for sub_title, sub_body in _split_md_subsections(title, body):
            seed_id = f"{_slug(product_name)}-doc-{_slug(sub_title)}"
            rows.append(
                {
                    "id": seed_id,
                    "text": f"# {sub_title}\n\n{sub_body}".strip(),
                    "metadata": {
                        "domain": domain_name,
                        "kind": kind,
                        "severity": severity,
                        "source": f"{source}#{_slug(title)}",
                        # Keep product hard rules out of NLPP hard-ban collection.
                        "collection_target": "lessons",
                        "product": product_name,
                        "seed_batch": batch,
                        "doc_id": _slug(title),
                        "importance": importance,
                    },
                }
            )
    return rows


def delete_product_seeds(
    product: str,
    collection: str = COLLECTION_CODING,
    *,
    also_products: tuple[str, ...] | list[str] = (),
    also_domains: tuple[str, ...] | list[str] = (),
    also_batches: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Remove seeded rows matching product / domain / seed_batch."""
    coll = _get_collection(collection)
    product_l = _slug(product)
    products = {product_l} | {_slug(p) for p in also_products if p}
    domains = {_slug(d) for d in also_domains if d} | {product_l}
    batches = {_product_batch(product_l)} | {
        str(b).strip() for b in also_batches if str(b).strip()
    }

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
        prod_raw = str(meta.get("product") or "").strip()
        domain_raw = str(meta.get("domain") or "").strip()
        prod = _slug(prod_raw) if prod_raw else ""
        domain = _slug(domain_raw) if domain_raw else ""
        if (prod and prod in products) or (domain and domain in domains) or batch in batches:
            deleted_ids.append(mid)

    if deleted_ids:
        chunk = 100
        for i in range(0, len(deleted_ids), chunk):
            coll.delete(ids=deleted_ids[i : i + chunk])
    return {
        "deleted": len(deleted_ids),
        "ids": deleted_ids,
        "collection": collection,
        "product": product_l,
    }


def delete_pentest_seeds(collection: str = COLLECTION_CODING) -> dict[str, Any]:
    """Remove prior pen-testing / legacy trace-viper seeded rows from a collection."""
    return delete_product_seeds(
        PRODUCT_PENTEST,
        collection=collection,
        also_products=LEGACY_PENTEST_PRODUCTS,
        also_domains=LEGACY_PENTEST_DOMAINS,
        also_batches=LEGACY_PENTEST_BATCHES,
    )


def delete_by_seed_ids(
    seed_ids: set[str] | list[str],
    collection: str = COLLECTION_CODING,
) -> dict[str, Any]:
    """Remove rows whose metadata.seed_id is in seed_ids (coding_lessons by default)."""
    want = {str(s).strip() for s in seed_ids if str(s).strip()}
    if not want:
        return {"deleted": 0, "ids": [], "collection": collection}

    coll = _get_collection(collection)
    deleted_ids: list[str] = []
    try:
        got = coll.get(include=["metadatas"])
    except Exception as exc:
        return {"deleted": 0, "ids": [], "error": str(exc), "collection": collection}

    ids = got.get("ids") or []
    metas = got.get("metadatas") or []
    for mid, meta in zip(ids, metas):
        meta = meta or {}
        sid = str(meta.get("seed_id") or "").strip()
        if sid in want:
            deleted_ids.append(mid)

    if deleted_ids:
        chunk = 100
        for i in range(0, len(deleted_ids), chunk):
            coll.delete(ids=deleted_ids[i : i + chunk])
    return {
        "deleted": len(deleted_ids),
        "ids": deleted_ids,
        "collection": collection,
    }


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
        product = str(meta_in.get("product") or "")
        scope = str(meta_in.get("scope") or "")
        if not scope:
            if batch == SOURCE_NLPP or collection == COLLECTION_HARD_BANS:
                scope = "nlpp"
            elif product == "general":
                scope = "general"
            elif product:
                scope = "product"
            else:
                scope = "learned"
        group = str(meta_in.get("group") or "")
        if not group:
            if scope == "nlpp":
                group = "nlpp-re"
            elif scope == "general":
                group = group_for_category(str(meta_in.get("doc_id") or meta_in.get("domain") or ""))
            elif scope == "product":
                group = "product-manual"
            else:
                group = "learned"
        family = str(meta_in.get("family") or family_for_product(product if product else ("nlpp" if scope == "nlpp" else "")))
        if scope == "nlpp":
            family = "nlpp-re"
        if scope == "general":
            family = "cross-project"

        meta = {
            "source": str(meta_in.get("source") or batch),
            "kind": kind,
            "seed_id": seed_id,
            "domain": str(meta_in.get("domain") or ""),
            "severity": str(meta_in.get("severity") or ""),
            "seed_batch": batch,
            "product": product,
            "scope": scope,
            "group": group,
            "family": family,
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


def load_product_jsonl(
    jsonl_path: Path,
    *,
    product: str | None = None,
    domain: str | None = None,
) -> tuple[list[dict[str, Any]], str, str]:
    """Load + stamp a product-catalog JSONL. Returns (rows, product, domain)."""
    path = Path(jsonl_path)
    product_name = _infer_product(path, product)
    domain_name = _slug(domain) if domain else product_name
    batch = _product_batch(product_name)
    raw = _load_jsonl(path)
    if not raw:
        return [], product_name, domain_name
    if not _is_product_catalog_row(raw[0]):
        raise ValueError(
            f"{path} is not a product-catalog JSONL "
            "(expected rows with category, title, text)"
        )
    rows = [
        normalize_product_catalog_row(
            row, product=product_name, domain=domain_name, batch=batch
        )
        for row in raw
    ]
    return rows, product_name, domain_name


def _apply_taxonomy(
    rows: list[dict[str, Any]],
    taxonomy: dict[str, str] | None,
) -> list[dict[str, Any]]:
    if not taxonomy:
        return rows
    stamped: list[dict[str, Any]] = []
    for row in rows:
        normalized = normalize_row(row)
        meta = stamp_taxonomy(
            dict(normalized.get("metadata") or {}),
            scope=taxonomy.get("scope"),
            group=taxonomy.get("group"),
            family=taxonomy.get("family"),
            product=taxonomy.get("product") or None,
        )
        normalized["metadata"] = meta
        stamped.append(normalized)
    return stamped


def seed_all(
    jsonl_path: Path | None = None,
    *,
    force: bool = False,
    taxonomy: dict[str, str] | None = None,
) -> dict[str, Any]:
    path = jsonl_path or DEFAULT_JSONL
    rows = _load_jsonl(path)
    # Default NLPP taxonomy when seeding the NLPP corpus.
    tax = taxonomy or {
        "scope": "nlpp",
        "group": "nlpp-re",
        "family": "nlpp-re",
    }
    rows = _apply_taxonomy(rows, tax)
    return _seed_rows(rows, force=force, source_label=str(path))


def seed_meta_jsonl(
    jsonl_path: Path,
    *,
    product: str | None = None,
    force: bool = False,
    replace: bool = False,
    taxonomy: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Ingest metadata-bearing JSONL (e.g. decomp rag_seeds export) into coding_lessons.

    Never writes to nlpp_hard_bans. On replace: purge by product/seed_batch and by
    seed_id list from the file (clears older unstamped copies of the same ids).
    """
    path = Path(jsonl_path)
    raw = _load_jsonl(path)
    if not raw:
        return {
            "source": str(path.resolve()),
            "inserted_count": 0,
            "skipped_count": 0,
            "total_rows": 0,
            "product": product or "",
        }

    first_meta = dict(raw[0].get("metadata") or {})
    product_name = _slug(
        product
        or first_meta.get("product")
        or "decomp-matching"
    )
    batch = str(
        first_meta.get("seed_batch") or _product_batch(product_name)
    ).strip()

    tax = dict(taxonomy or {})
    tax.setdefault("product", product_name)
    tax.setdefault("scope", "product")
    tax.setdefault("group", "product-manual")
    tax.setdefault("family", family_for_product(product_name))

    rows = _apply_taxonomy(raw, tax)
    # Ensure every row carries the shared batch for later replace.
    for row in rows:
        meta = dict(row.get("metadata") or {})
        meta.setdefault("seed_batch", batch)
        meta.setdefault("collection_target", "lessons")
        row["metadata"] = meta

    purged: dict[str, Any] = {}
    if replace:
        seed_ids = {
            str(r.get("id") or r.get("seed_id") or "").strip()
            for r in rows
            if str(r.get("id") or r.get("seed_id") or "").strip()
        }
        by_ids = delete_by_seed_ids(seed_ids, COLLECTION_CODING)
        by_prod = delete_product_seeds(
            product_name,
            COLLECTION_CODING,
            also_batches=(batch, "seed_nlpp_decomp"),
            also_domains=(),
        )
        purged = {
            "by_seed_id": by_ids.get("deleted", 0),
            "by_product": by_prod.get("deleted", 0),
        }

    summary = _seed_rows(rows, force=force, source_label=str(path.resolve()))
    summary["product"] = product_name
    summary["files"] = [str(path.resolve())]
    if purged:
        summary["purged"] = purged
    return summary


def dry_run_meta_jsonl(jsonl_path: Path) -> list[dict[str, Any]]:
    return dry_run_rows(_load_jsonl(Path(jsonl_path)))


def seed_product_jsonl(
    jsonl_path: Path,
    *,
    product: str | None = None,
    domain: str | None = None,
    force: bool = False,
    replace: bool = False,
    taxonomy: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Ingest a product-catalog JSONL into coding_lessons."""
    path = Path(jsonl_path)
    rows, product_name, domain_name = load_product_jsonl(
        path, product=product, domain=domain
    )
    purged = None
    if replace:
        purged = delete_product_seeds(product_name, COLLECTION_CODING)
    tax = dict(taxonomy or {})
    tax.setdefault("product", product_name)
    if product_name == "general":
        tax.setdefault("scope", "general")
        tax.setdefault("family", "cross-project")
    else:
        tax.setdefault("scope", "product")
        tax.setdefault("group", "product-manual")
        tax.setdefault("family", family_for_product(product_name))
    # Keep per-row general groups from category when seeding general/*.jsonl
    if product_name == "general":
        for row in rows:
            meta = dict(row.get("metadata") or {})
            meta = stamp_taxonomy(
                meta,
                scope="general",
                group=group_for_category(str(meta.get("doc_id") or "")),
                family="cross-project",
                product="general",
            )
            row["metadata"] = meta
    else:
        rows = _apply_taxonomy(rows, tax)
    summary = _seed_rows(rows, force=force, source_label=str(path.resolve()))
    summary["product"] = product_name
    summary["domain"] = domain_name
    summary["files"] = [str(path.resolve())]
    if purged is not None:
        summary["purged"] = {"deleted": purged.get("deleted", 0)}
    return summary


def seed_pack(
    pack_dir: Path,
    *,
    force: bool = False,
    replace: bool = False,
    taxonomy: dict[str, str] | None = None,
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

    tax = dict(taxonomy or {})
    tax.setdefault("scope", "product")
    tax.setdefault("group", "product-manual")
    tax.setdefault("family", "appsec")
    tax.setdefault("product", PRODUCT_PENTEST)
    rows = _apply_taxonomy(rows, tax)

    summary = _seed_rows(rows, force=force, source_label=str(root))
    summary["files"] = [str(p) for p in paths]
    summary["product"] = PRODUCT_PENTEST
    summary["domain"] = DOMAIN_PENTEST
    if purged is not None:
        summary["purged"] = {"deleted": purged.get("deleted", 0)}
    return summary


def seed_md(
    md_path: Path,
    *,
    product: str | None = None,
    domain: str | None = None,
    force: bool = False,
    replace: bool = False,
    taxonomy: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Ingest a ## Document: markdown rag-seed file into coding_lessons."""
    path = Path(md_path)
    product_name = _infer_product(path, product)
    domain_name = _slug(domain) if domain else product_name
    rows = parse_rag_seed_md(path, product=product_name, domain=domain_name)

    purged = None
    if replace:
        purged = delete_product_seeds(product_name, COLLECTION_CODING)

    tax = dict(taxonomy or {})
    tax.setdefault("scope", "product")
    tax.setdefault("group", "product-manual")
    tax.setdefault("family", family_for_product(product_name))
    tax.setdefault("product", product_name)
    rows = _apply_taxonomy(rows, tax)

    summary = _seed_rows(rows, force=force, source_label=str(path.resolve()))
    summary["product"] = product_name
    summary["domain"] = domain_name
    summary["files"] = [str(path.resolve())]
    if purged is not None:
        summary["purged"] = {"deleted": purged.get("deleted", 0)}
    return summary


def seed_rag_dir(
    rag_dir: Path,
    *,
    product: str | None = None,
    domain: str | None = None,
    force: bool = False,
    replace: bool = False,
    taxonomy: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Ingest a product rag/ folder (SEED.md + qa_pairs.jsonl + optional JSONL)."""
    rows, product_name, domain_name, files = load_rag_dir(
        rag_dir, product=product, domain=domain
    )
    purged = None
    if replace:
        purged = delete_product_seeds(product_name, COLLECTION_CODING)
    tax = dict(taxonomy or {})
    tax.setdefault("scope", "product")
    tax.setdefault("group", "product-manual")
    tax.setdefault("family", family_for_product(product_name))
    tax.setdefault("product", product_name)
    rows = _apply_taxonomy(rows, tax)
    summary = _seed_rows(rows, force=force, source_label=str(Path(rag_dir).resolve()))
    summary["product"] = product_name
    summary["domain"] = domain_name
    summary["files"] = files
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


def dry_run_product_jsonl(
    jsonl_path: Path,
    *,
    product: str | None = None,
    domain: str | None = None,
) -> list[dict[str, Any]]:
    rows, _, _ = load_product_jsonl(jsonl_path, product=product, domain=domain)
    return dry_run_rows(rows)


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


def dry_run_md(
    md_path: Path,
    *,
    product: str | None = None,
    domain: str | None = None,
) -> list[dict[str, Any]]:
    return dry_run_rows(parse_rag_seed_md(md_path, product=product, domain=domain))


def dry_run_rag_dir(
    rag_dir: Path,
    *,
    product: str | None = None,
    domain: str | None = None,
) -> list[dict[str, Any]]:
    rows, _, _, _ = load_rag_dir(rag_dir, product=product, domain=domain)
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
