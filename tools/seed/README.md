# Blossom RAG seed catalog

Seeds are organized by **scope** and **group**, then stamped into Chroma with
`family` / `product` so retrieval stays useful across many projects.

## Layout

```
tools/seed/
  catalog.json              # registry of all sources
  general/                  # cross-project lessons (always retrieved)
    process.jsonl
    security_ops.jsonl
    data.jsonl
    ml_local.jsonl
    architecture.jsonl
  nlpp/                     # NLPP RE hard bans + lessons
    chroma_lessons.jsonl
    lessons.json            # legacy P5 pack
  products/manifest.json    # family → product map (docs)
```

## Taxonomy

| Field | Values |
|-------|--------|
| `scope` | `general` (always) · `nlpp` · `product` (only if workspace matches) · `learned` |
| `group` | `process` · `security-ops` · `data` · `ml-local` · `architecture` · `nlpp-re` · `product-manual` |
| `family` | `cross-project` · `homelab-media` · `local-diffusion` · `appsec` · `nlpp-re` · `decomp-matching` |
| `product` | e.g. `anime-db-stream`, `waifu-redraw`, `decomp-matching`, `general` |

**Families**

| Family | Products |
|--------|----------|
| `homelab-media` | anime-db-stream, anime-db-tracker |
| `local-diffusion` | waifu-redraw, instagram-model-ai, animewallpaper-generator |
| `appsec` | pen-testing (Trace Viper pack) |
| `nlpp-re` | NLPP EngPatcher hard bans + lessons |
| `decomp-matching` | Shared matching-decomp loop (any title; needles: `decomp`, `ctrdecomp`, `code.bin`, …) |
| `cross-project` | `general/*` lessons |

ChatRouter coding RAG uses `query_coding_lessons`: keeps `general` / `nlpp` /
`learned`, plus `product` manuals only when editor paths match that product/family.

## Apply everything

```powershell
python tools/seed/seed_chroma_lessons.py --catalog --dry-run
python tools/seed/seed_chroma_lessons.py --catalog --replace
```

### Apply one group / scope

```powershell
python tools/seed/seed_chroma_lessons.py --catalog --scope general --replace
python tools/seed/seed_chroma_lessons.py --catalog --group ml-local --replace
python tools/seed/seed_chroma_lessons.py --catalog --scope product --replace
```

## One-off sources (still supported)

```powershell
# NLPP default JSONL
python tools/seed/seed_chroma_lessons.py --dry-run
python tools/seed/seed_chroma_lessons.py

# Product pack / dir / md / catalog JSONL
python tools/seed/seed_chroma_lessons.py --pack "C:\Users\Zepse\Documents\trace-viper-pen-tester\rag-seeds" --replace
python tools/seed/seed_chroma_lessons.py --dir "C:\Users\Zepse\Documents\AnimeWallpaper Generator\rag" --replace
python tools/seed/seed_chroma_lessons.py --md "C:\Users\Zepse\Documents\anime-db-stream\docs\rag-seed.md" --replace
python tools/seed/seed_chroma_lessons.py --jsonl "C:\Users\Zepse\Documents\Instagram Model AI\docs\llm_train\instagram_model_ai_rag_seed.jsonl" --replace
```

## Collections

| `collection_target` / kind | Chroma collection |
|----------------------------|-------------------|
| NLPP `hard_bans` | `nlpp_hard_bans` (always on coding) |
| everything else | `coding_lessons` (scoped retrieval) |

## Verify

```powershell
Invoke-RestMethod "http://127.0.0.1:8081/v1/memory/coding?q=letterbox%20never%20stretch&n=5"
```

## Legacy

```powershell
python tools/seed/seed_nlpp_lessons.py
```

Prefer `seed_chroma_lessons.py --catalog` for new knowledge.
