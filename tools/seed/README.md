# NLPP Chroma lesson seeds

Primary headstart for Blossom coding/RE: JSONL corpus → Chroma `nlpp_hard_bans` + `coding_lessons`.

## Quick apply

From repo root (ChatRouter not required):

```powershell
python tools/seed/seed_chroma_lessons.py --dry-run
python tools/seed/seed_chroma_lessons.py
```

### Pen-testing rag-seeds pack

Ingest `chunks/normalized_for_vectorstore.jsonl` (or `corpus.jsonl`) + `qa/qa_pairs.jsonl` into `coding_lessons` with `product=pen-testing` / `domain=pen-testing` (safety_critical → importance 10; never mixed into `nlpp_hard_bans`):

```powershell
python tools/seed/seed_chroma_lessons.py --pack "C:\Users\Zepse\Documents\trace-viper-pen-tester\rag-seeds" --dry-run
python tools/seed/seed_chroma_lessons.py --pack "C:\Users\Zepse\Documents\trace-viper-pen-tester\rag-seeds" --replace
```

`--replace` purges prior pen-testing / legacy `trace-viper` seed rows before insert.

Idempotent by `seed_id` in metadata. Re-run after wiping `Mind/chromadb/` or after editing the JSONL.

## Corpus

| File | Role |
|------|------|
| `nlpp_chroma_lessons.jsonl` | Atomic lessons (symptom → cause → do/don't → pointer) |
| `nlpp_lessons.json` | Legacy P5 four-lesson pack (`seed_nlpp_lessons.py`) |

### JSONL row shape

```json
{"id": "ban-…", "text": "Symptom: …\nCause: …\nDo: …\nDon't: …\nPointer: …", "metadata": {"domain": "img", "kind": "hard_ban", "severity": "critical", "source": "technical.md#§0", "collection_target": "hard_bans", "pkg": 5238}}
```

| `collection_target` | Chroma collection |
|---------------------|-------------------|
| `hard_bans` | `nlpp_hard_bans` (always retrieved on coding, top-k=`HARD_BANS_TOP_K`) |
| `lessons` | `coding_lessons` (RAG, top-k=`CODING_LESSONS_TOP_K`) |

Severity → importance: critical=10, high=9, medium=7.

## Retrieval (ChatRouter)

On coding route (non-sequential):

1. Always query `nlpp_hard_bans` (even on TINY tier).
2. Query `coding_lessons` unless TINY+editor skip.
3. System constitution also lives in `PythonScripts/coding_rules.txt` (NLPP CONSTITUTION).

Env knobs: see `PythonScripts/.env.example` (`CHROMA_COLLECTION_HARD_BANS`, `HARD_BANS_TOP_K`, `CODING_LESSONS_TOP_K`, …).

## Verify

With ChatRouter up:

```powershell
Invoke-RestMethod "http://127.0.0.1:8081/v1/memory/coding?q=img.bin%20zlib&n=5"
```

Hard bans are a separate collection (not listed by that endpoint); dry-run / seed summary reports both.

## Legacy

```powershell
python tools/seed/seed_nlpp_lessons.py
```

Prefer `seed_chroma_lessons.py` for new NLPP knowledge.
