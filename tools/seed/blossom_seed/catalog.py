"""Seed catalog: groups, families, and multi-source apply."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SEED_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = SEED_ROOT / "catalog.json"

# product → family (used when stamping rows)
PRODUCT_FAMILY = {
    "general": "cross-project",
    "decomp-matching": "decomp-matching",
    "nlpp-decomp": "decomp-matching",
    "anime-db-stream": "homelab-media",
    "anime-db-tracker": "homelab-media",
    "waifu-redraw": "local-diffusion",
    "instagram-model-ai": "local-diffusion",
    "animewallpaper-generator": "local-diffusion",
    "pen-testing": "appsec",
    "trace-viper": "appsec",
    "traceviper": "appsec",
}

CATEGORY_TO_GROUP = {
    "process": "process",
    "policy": "process",
    "security": "security-ops",
    "ops": "security-ops",
    "data": "data",
    "ml": "ml-local",
    "architecture": "architecture",
    "identity": "ml-local",
    "workflow": "product-manual",
    "product": "product-manual",
    "train": "ml-local",
    "generate": "ml-local",
    "wan": "ml-local",
    "settings": "product-manual",
    "troubleshooting": "product-manual",
    "engineering": "product-manual",
}


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    catalog_path = Path(path) if path else DEFAULT_CATALOG
    data = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError(f"Invalid catalog: {catalog_path}")
    return data


def resolve_source_path(raw: str, *, catalog_path: Path) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    # Relative paths are from tools/seed/
    return (SEED_ROOT / p).resolve()


def family_for_product(product: str) -> str:
    key = (product or "").strip().lower()
    return PRODUCT_FAMILY.get(key, "product-manual" if key else "cross-project")


def group_for_category(category: str, *, default: str = "product-manual") -> str:
    return CATEGORY_TO_GROUP.get((category or "").strip().lower(), default)


def stamp_taxonomy(
    meta: dict[str, Any],
    *,
    scope: str | None = None,
    group: str | None = None,
    family: str | None = None,
    product: str | None = None,
) -> dict[str, Any]:
    out = dict(meta)
    prod = str(product if product is not None else out.get("product") or "").strip()
    if prod:
        out["product"] = prod
    out["scope"] = str(scope or out.get("scope") or ("general" if prod == "general" else "product"))
    out["family"] = str(family or out.get("family") or family_for_product(prod))
    if group:
        out["group"] = str(group)
    elif not out.get("group"):
        if out["scope"] == "general":
            out["group"] = group_for_category(str(out.get("doc_id") or out.get("domain") or ""), default="process")
        elif out["scope"] == "nlpp":
            out["group"] = "nlpp-re"
        else:
            out["group"] = "product-manual"
    return out


def infer_workspace_targets(
    path_hints: list[str] | None,
    catalog: dict[str, Any] | None = None,
) -> tuple[set[str], set[str]]:
    """Return (allowed_products, allowed_families) from editor/workspace path hints."""
    blob = " ".join(path_hints or []).lower().replace("\\", "/")
    products: set[str] = set()
    families: set[str] = {"cross-project"}

    cat = catalog or {}
    for src in cat.get("sources") or []:
        if not isinstance(src, dict):
            continue
        product = str(src.get("product") or "").strip()
        family = str(src.get("family") or "").strip()
        if not product and not family:
            continue
        matchers = [product] if product else []
        fam_match = ((cat.get("families") or {}).get(family) or {}).get("match") or []
        matchers.extend(str(m) for m in fam_match)
        if any(m and m.lower() in blob for m in matchers):
            if product:
                products.add(product)
            if family:
                families.add(family)

    # Fallback path heuristics when catalog missing
    heuristics = {
        "anime-db-stream": "homelab-media",
        "anime-db-tracker": "homelab-media",
        "waifu redraw": "local-diffusion",
        "waifu-redraw": "local-diffusion",
        "instagram model ai": "local-diffusion",
        "animewallpaper": "local-diffusion",
        "trace-viper": "appsec",
        "pen-tester": "appsec",
    }
    for needle, family in heuristics.items():
        if needle in blob:
            families.add(family)
            for prod, fam in PRODUCT_FAMILY.items():
                if fam == family and prod not in {"general", "trace-viper", "traceviper"}:
                    products.add(prod)

    return products, families


def seed_catalog(
    catalog_path: Path | None = None,
    *,
    groups: list[str] | None = None,
    scopes: list[str] | None = None,
    force: bool = False,
    replace: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply selected catalog sources. Import seeder funcs lazily to avoid cycles."""
    from .chroma_lessons import (  # noqa: WPS433
        dry_run_md,
        dry_run_meta_jsonl,
        dry_run_pack,
        dry_run_product_jsonl,
        dry_run_rag_dir,
        dry_run as dry_run_nlpp,
        seed_all,
        seed_md,
        seed_meta_jsonl,
        seed_pack,
        seed_product_jsonl,
        seed_rag_dir,
    )

    catalog_file = Path(catalog_path) if catalog_path else DEFAULT_CATALOG
    catalog = load_catalog(catalog_file)
    want_groups = {g.strip() for g in (groups or []) if g.strip()}
    want_scopes = {s.strip() for s in (scopes or []) if s.strip()}

    results: list[dict[str, Any]] = []
    replaced_products: set[str] = set()
    for src in catalog["sources"]:
        if not isinstance(src, dict):
            continue
        group = str(src.get("group") or "")
        scope = str(src.get("scope") or "")
        if want_groups and group not in want_groups:
            continue
        if want_scopes and scope not in want_scopes:
            continue

        path = resolve_source_path(str(src.get("path") or ""), catalog_path=catalog_file)
        kind = str(src.get("kind") or "")
        product = str(src.get("product") or "") or None
        entry: dict[str, Any] = {
            "id": src.get("id"),
            "group": group,
            "scope": scope,
            "family": src.get("family"),
            "product": product,
            "kind": kind,
            "path": str(path),
        }

        if dry_run:
            try:
                if kind == "nlpp_jsonl":
                    rows = dry_run_nlpp(path)
                elif kind == "meta_jsonl":
                    rows = dry_run_meta_jsonl(path)
                elif kind == "product_jsonl":
                    rows = dry_run_product_jsonl(path, product=product)
                elif kind == "md":
                    rows = dry_run_md(path, product=product)
                elif kind == "dir":
                    rows = dry_run_rag_dir(path, product=product)
                elif kind == "pack":
                    rows = dry_run_pack(path)
                else:
                    raise ValueError(f"Unknown kind {kind}")
                entry["rows"] = len(rows)
                entry["status"] = "ok"
            except Exception as exc:
                entry["status"] = "error"
                entry["error"] = str(exc)
            results.append(entry)
            continue

        try:
            taxonomy = {
                "scope": scope,
                "group": group,
                "family": str(src.get("family") or ""),
            }
            # Purge each product/family at most once when applying the whole catalog.
            do_replace = False
            if replace:
                replace_key = product or f"scope:{scope}"
                if replace_key not in replaced_products:
                    do_replace = True
                    replaced_products.add(replace_key)

            if kind == "nlpp_jsonl":
                if do_replace:
                    from .chroma_lessons import delete_product_seeds  # noqa: WPS433
                    from SemanticMemory import COLLECTION_CODING, COLLECTION_HARD_BANS

                    # NLPP rows are keyed by seed_batch more than product.
                    delete_product_seeds(
                        "nlpp",
                        COLLECTION_CODING,
                        also_batches=("seed_chroma_nlpp",),
                        also_domains=(),
                    )
                    delete_product_seeds(
                        "nlpp",
                        COLLECTION_HARD_BANS,
                        also_batches=("seed_chroma_nlpp",),
                        also_domains=(),
                    )
                summary = seed_all(
                    path,
                    force=force or do_replace,
                    taxonomy={
                        **taxonomy,
                        "scope": "nlpp",
                        "group": "nlpp-re",
                        "family": "nlpp-re",
                    },
                )
            elif kind == "meta_jsonl":
                summary = seed_meta_jsonl(
                    path,
                    product=product,
                    force=force or do_replace,
                    replace=do_replace and bool(product),
                    taxonomy={
                        **taxonomy,
                        "product": product or "decomp-matching",
                        "scope": scope or "product",
                        "group": group or "product-manual",
                        "family": str(src.get("family") or "decomp-matching"),
                    },
                )
            elif kind == "product_jsonl":
                summary = seed_product_jsonl(
                    path,
                    product=product,
                    force=force or do_replace,
                    replace=do_replace and bool(product),
                    taxonomy=taxonomy,
                )
            elif kind == "md":
                summary = seed_md(
                    path,
                    product=product,
                    force=force or do_replace,
                    replace=do_replace,
                    taxonomy=taxonomy,
                )
            elif kind == "dir":
                summary = seed_rag_dir(
                    path,
                    product=product,
                    force=force or do_replace,
                    replace=do_replace,
                    taxonomy=taxonomy,
                )
            elif kind == "pack":
                summary = seed_pack(
                    path,
                    force=force or do_replace,
                    replace=do_replace,
                    taxonomy=taxonomy,
                )
            else:
                raise ValueError(f"Unknown kind {kind}")
            entry["summary"] = {
                "inserted_count": summary.get("inserted_count"),
                "skipped_count": summary.get("skipped_count"),
                "purged": summary.get("purged"),
            }
            entry["status"] = "ok"
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = str(exc)
        results.append(entry)

    return {
        "catalog": str(catalog_file.resolve()),
        "sources": results,
        "ok": sum(1 for r in results if r.get("status") == "ok"),
        "errors": sum(1 for r in results if r.get("status") == "error"),
    }
