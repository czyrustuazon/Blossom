# Blossom

Local-first personal companion: llama.cpp GGUFs + FastAPI ChatRouter (`:8081`) + SQLite + Chroma, with optional cloud escalation (Cursor, Gemini, Claude), web search, spoken replies, and measurable coding improvement.

## Quick start

1. Populate **`Brains/`** (GGUFs + `llama-server` runtime) — see **[Brains/README.md](./Brains/README.md)**.
2. Copy `PythonScripts/.env.example` → `PythonScripts/.env` and fill keys / paths.
3. `pip install -r PythonScripts/requirements.txt`
4. Start:

```powershell
& ".\start-server.ps1"
```

Point clients at `http://127.0.0.1:8081/v1/chat/completions` (or your Tailscale host from `.env` — never commit the real IP; use `XXX.XXX.XXX.XXX` in docs).

## Clients

| Client | Role |
|--------|------|
| **Blossom Companion** (`Documents\Blossom Companion`) | Chat UI: personas, JA/EN locale, spoken replies, 👍/👎 on coding answers |
| **Blossom Assistant** (`Documents\Blossom Assistant`) | VS Code extension: agent loop, Apply/delete, escalation, editor context |

## Research pipeline (shared)

ChatRouter gates web research (`skip` / `simple` / `deep`) via [`PythonScripts/ResearchPipeline.py`](./PythonScripts/ResearchPipeline.py). Deep mode plans multiple queries, searches in parallel, optionally fetches page text, and synthesizes a cited brief into `web_knowledge`. Progress streams as `blossom.thought` steps (`research_gate`, `research_plan`, `research_search`, `research_fetch`, `research_synth`).

**API (Blossom Assistant hook):** `POST /v1/research`

```json
{ "query": "latest FastAPI lifespan docs", "coding": true }
```

Response: `{ "ok": true, "brief": "...", "mode": "skip|simple|deep", "sources": [...], "queries": [...] }`.

In the Assistant orchestrator, call this when a task looks documentation-heavy and prepend `brief` to the model context. Do not reimplement planner/search roles in TypeScript — ChatRouter owns the pipeline. Env: `RESEARCH_PIPELINE_ENABLED`, `RESEARCH_DEEP_ENABLED`, `RESEARCH_MAX_QUERIES`, `RESEARCH_TIMEOUT_SEC` (see `.env.example`).

## Vision

Blossom is a **cost-aware hybrid stack**, not a bet that one local model replaces Cursor:

```
Today (RTX 4090, 24 GB VRAM):
  Local Qwen 30B MoE + DeepSeek ladder  →  routine coding cheaply
  Cursor Agent                           →  hard RE, Ghidra MCP, multi-tool sessions
  Chroma RAG + SQLite feedback           →  remembers what cloud taught

Future (70B-capable hardware):
  70B-class local coder                  →  fewer escalations
  Cursor Agent                           →  still top tier for nasty RE / agent work
  Optional LoRA                          →  frozen output habits only (fences, Apply protocol)
```

| Claim | Verdict |
|-------|---------|
| Local 30B + DeepSeek for daily coding | **Merit** — production ladder |
| Learn successes into Chroma (RAG) | **Merit** — best ROI; reversible via 👍/👎 |
| Escalate to Cursor when stuck | **Merit** — tools/MCP for hard tier |
| Save money vs Cursor-only | **Merit** — if Blossom owns ~70% routine slice |
| Local **fully replaces** Cursor Agent | **Pipe dream** — agent loop, MCP, indexing stay valuable |
| RAG = “training the GGUF weights” | **Pipe dream** (wording) — RAG is system memory; LoRA is separate |
| 72B hybrid on single 4090 with CPU spill | **Rejected** — ~0.35 tok/s; see `PROGRESS.md` |

**Anti-goals:** replace Cursor for NLPP reverse-engineering entirely; pretend local Qwen sees image pixels; expect pixel-perfect BCLIM matching without MAD scripts.

Full assessment and implementation checklists live in **[MustDo.md](./MustDo.md)** (active spec).

## Hybrid workflow — which tool when

| Task | Tool |
|------|------|
| Routine edits, Apply cards, small refactors | **Blossom Assistant** (local coder) |
| NLPP / Ghidra / long RE, MCP, terminal chains | **Cursor** (directly or via escalate) |
| Companion chat, JA study, voice | **Blossom Companion** |
| Text-only cloud fallback | Gemini → Claude via ChatRouter |
| Texture / screenshot analysis | **Cursor escalate** (local coder is text-only) |

Each IDE owns a **lane**. Overhead of multiple tools is real; routing by task keeps cost down.

## Escalation (Blossom Assistant)

When local Qwen is uncertain, the extension can escalate to cloud agents. Learning uses **👍 Correct** / **👎 Incorrect** on the reply — not auto-learn or clipboard import.

| Marker / action | Behavior |
|-----------------|----------|
| `ESCALATE_CURSOR` in local reply | Offer Cursor Agent (SDK) with compressed session handoff |
| `ESCALATE_GEMINI` | Gemini text completion fallback |
| Manual **Copy Cursor handoff** | Clipboard compressed context for Cursor IDE |
| **Retry with local Blossom** (P2-deescalate) | After cloud answer, re-run locally with cloud facts injected |
| **Apply from cloud** (P3) | Fenced `path=` blocks in cloud text become Apply cards |

**Setup (extension-side):**

- Cursor: API key in Blossom Assistant settings; `@cursor/sdk` for agent escalate
- Gemini / Claude: keys in extension or ChatRouter `.env` for cloud fallback
- Confirm-before-call: escalation picker (P1c-cloud) — user chooses provider

Cloud handoff includes **compressed prior conversation** (§ Handoff compression below) so multi-turn context survives the hop.

## Images & vision routing

Local Qwen3-Coder-30B is **text-only** in this deployment — it cannot parse PNG/JPEG pixels.

- Default (`vision.onAttach=escalate`): image attach → Cursor handoff with file paths + metadata (dimensions, mean RGB, alpha hints)
- Stay-local option: metadata text appended to prompt with explicit “no vision” warning
- Do not claim the local model “viewed” an image when only metadata was injected

For romhack texture ID (e.g. NLPP BCLIM), prefer **script evidence** (MAD, `image_map.py`, `bclimutil`) over filename guessing — even vision models are unreliable at exact texture identity.

## Handoff compression

Before every cloud escalate, Blossom Assistant compresses the session once; ChatRouter can further compress for `_cloud_facts()` reuse across Gemini → Claude.

| Layer | Where |
|-------|--------|
| Extension handoff | Shared `compressHandoff` before Cursor / Gemini / Claude |
| Backend cloud appendix | `CloudHandoffCompressor` + `prepare_cloud_coding_prompt` in ChatRouter |

Env tuning (see `PythonScripts/.env.example`): `HANDOFF_COMPRESS_ENABLED`, `HANDOFF_MAX_CHARS`, etc.

## Learning — RAG first, LoRA later

**Phase A — RAG (now):**

1. Successful coding paths can auto-learn into Chroma `coding_lessons`
2. **👍/👎** curates noise via `feedback_turns` (SQLite)
3. Domain lessons: `python tools/seed/seed_chroma_lessons.py` → `nlpp_hard_bans` + `coding_lessons` (see `tools/seed/README.md`). Legacy four-pack: `seed_nlpp_lessons.py`.
4. API: `POST /v1/memory/coding` for extension-verified lessons

**Phase B — Eval harness** (`tools/eval/`):

```powershell
python tools/eval/run_eval.py run --corpus php-modernization
python tools/eval/run_eval.py report
```

Corpus-agnostic checks (file contains, regex, shell, response-only for RE). Results in `Mind/eval_results.db`. On startup, `start-server.ps1` can run a dry-run eval in the background (`EVAL_ON_STARTUP=true`, `EVAL_ON_STARTUP_DRY_RUN_ONLY`, `EVAL_CORPUS`).

**Phase C — LoRA (optional):** frozen output habits only — see **[tools/lora/README.md](./tools/lora/README.md)**.

```powershell
python tools/lora/export_dataset.py
# GPU venv: pip install -r tools/lora/requirements-train.txt
python tools/lora/train_qlora.py
```

Export 👍 coding turns + optional `coding_rules.txt` habits → ShareGPT/Alpaca JSONL → QLoRA → merge/GGUF → `Brains/models/coding/`.

**Desktop workflow guide:** `Documents\Project Organizer\blossom-coding-workflow\` — **Project Organizer → Blossom Coding Workflow → Launch**.

## Hardware & models

**Current (RTX 4090, 24 GB):** Primary coder is **Qwen3-Coder-30B-A3B** MoE (Q4_K_M) with DeepSeek ladder fallback. Full-GPU residency — no CPU spill.

**Future 70B:** Requires new hardware (48 GB+ single GPU, dual 24 GB, or dedicated inference box). Do **not** repeat Qwen2.5-72B Q3_K_M with layer spill on 4090 — measured unusable. When funded, add preset to `Brains/model-presets.json` and update `CODER_MODELS`.

Model layout and download: **[Brains/README.md](./Brains/README.md)**.

## Optional: spoken replies (Voice)

See **[Voice/README.md](./Voice/README.md)**.

1. Drop RVC packs under `Voice/characters/<Name>/{Jpn,Eng}/` (`.pth` + `.index`).
2. Create a CUDA venv for Voice and set `VOICE_PYTHON` (see Voice README).
3. Set `VOICE_ENABLED=true` in `PythonScripts/.env`.
4. In Companion → Personality, pick **Voice pack** (`voice_id`).
5. `start-server.ps1` launches the Voice service on `:8090`.

| Locale | Pipeline |
|--------|----------|
| Japanese | Style-Bert-VITS2 → character RVC |
| English | Edge TTS → character RVC |

## Where we're at

| Doc | Purpose |
|-----|---------|
| **[PROGRESS.md](./PROGRESS.md)** | Architecture, session log, lessons learned |
| **[MustDo.md](./MustDo.md)** | Active implementation spec, testing checklist, API reference |

**Shipped (2026-08-02):** P0–P4 (Cursor escalate, manual handoff, vision routing, interrupt, cloud picker, de-escalate, cloud compression, Apply from cloud, eval harness + startup eval), **P5** NLPP lesson seeds, **P6** LoRA export/train pipeline.
