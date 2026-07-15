# Blossom — progress & status

Local-first personal companion stack. **Not** a fine-tuned foundation model.

This document is the running “where we are” note for the Blossom backend (`Documents\Blossom`). The VS Code client lives in a sibling folder: `Documents\Blossom Assistant`.

**Last updated: 2026-07-13** — mind “commit” vs LoRA/safetensors decision + earlier feedback/ladder work.

---

## What this repo is

It stitches:

- local GGUFs via llama.cpp (`llama-server`)
- a FastAPI OpenAI-compatible router (port **8081**)
- SQLite short-term chat + personality metrics
- Chroma long-term semantic memory
- optional Claude/Gemini as last resort
- optional web search saved back into Chroma

**One-shot start:**

```powershell
& "C:\Users\Zepse\Documents\Blossom\start-server.ps1"
```

Clients → `http://127.0.0.1:8081/v1/chat/completions` (not bare `:11434`).

**Split of responsibility**

| Concern | Owner |
|--------|--------|
| Routing, RAG, cloud fallback, learn into Chroma | ChatRouter (this repo) |
| Disk truth (exists / unused / Apply / **delete**) | Blossom Assistant (extension) |
| Fine-tune weights from experience | Not used — RAG + code fixes instead |

---

## Layout

```
Blossom/
  Brains/
    runtime/               # llama-server + CUDA DLLs
    models/...             # conversational + coding GGUFs (gitignored)
    add-model.ps1          # download any HF GGUF into models/
    model-presets.json     # known presets (e.g. DeepSeek coder)
  Mind/                    # CompanionMind.db, chromadb/, pid/logs, backups/, audio/
  PythonScripts/           # ChatRouter, MemoryUpdater, LocalModels, VoiceClient, …
  Voice/                   # FastAPI TTS+RVC service (:8090)
    characters/            # RVC packs (gitignored); code stays beside them
  start-server.ps1
```

Siblings:

- `Blossom Companion/` — Nuxt chat UI (personas, locale, voice playback)
- `Blossom Assistant/` — VS Code extension (Apply, editor context, auto-apply, memory POST after Gemini escalate)

---

## What we’ve built

### Backend pieces

| Piece | Role |
|--------|------|
| `Brains/runtime/` | Trimmed CUDA 12 llama.cpp Windows binaries |
| `Brains/models/` | Conversational + coding GGUF slots |
| `Mind/` | SQLite mind, Chroma store, llama pid/role/logs, TTS WAV cache |
| `MemoryUpdater.py` | SQLite mind, multi-persona book, `voice_id`, reflection every N turns |
| `SemanticMemory.py` | Chroma: `relationship_life`, `coding_lessons`, `language_lessons`, `web_knowledge` |
| `FeedbackStore.py` | SQLite `feedback_turns`; correctness up/down for coding + Japanese teaching |
| `HistoryCompactor.py` | Old SQLite chats → life memories, prune/VACUUM |
| `LocalModels.py` | Resolve GGUF paths (abs or under `Brains/models/`); ordered coder ladder |
| `LlamaServerManager.py` | Hot-swap persona ↔ any coder GGUF on one GPU |
| `download_local_model.py` | HF download used by `Brains/add-model.ps1` |
| `ChatRouter.py` | Route casual / coding / Japanese; coder ladder then cloud; thoughts SSE; learn; feedback; voice attach |
| `VoiceClient.py` | Emotion → speak; proxy `/v1/voices`; cache WAVs under `Mind/audio/` |
| `WebSearch.py` | DuckDuckGo / Brave / Serper / Bing → inject + store |
| `EditorContext.py` | Select → chunk → rank → pack for coder budget |
| `coding_rules.txt` | PLAN→EXECUTE→VERIFY, CREATE vs EDIT, fences, link/orphan rules |
| `Voice/` | Warm SBV2 + lazy RVC; JA/EN; pack discovery under `characters/` |
| `.env` / `.env.example` | Keys, model paths / `CODER_MODELS`, collections, search, cloud order, voice |
| `Brains/add-model.ps1` | Agnostic “add a local LLM” — preset or `--Repo`/`--File` into `models/` |

### Newer backend work

Dated when landed in this tree (newest first). Detail → Session log.

- **(2026-07-13 evening)** Correctness feedback: `POST /v1/feedback`, `FeedbackStore`, `language_lessons`, Companion Correct/Incorrect
- **(2026-07-13 evening)** Local coder ladder: `CODER_MODELS` / `CODER_ALT_MODEL_PATH`; DeepSeek-Coder-V2-Lite Q4 alt; `/health` ladder fields
- **(2026-07-13 evening)** Agnostic model add: `Brains/add-model.ps1` + `model-presets.json` + `download_local_model.py`
- **(2026-07-13)** Persona CoT off (`PERSONA_REASONING=off`); flash-attn; Qwen3-14B persona plan
- **(2026-07-13)** Voice EN tuning (AvaNeural, pitch_en); speech sanitization; speakable `neutral`
- **(2026-07-13)** Persona catchphrase / remix anti-echo hardening
- **(2026-07-13)** History compaction after llama ready (`COMPACT_ON_STARTUP`)
- **(2026-07-12)** Multi-character Voice packs + Companion `voice_id` dropdown
- **(2026-07-12)** Spoken replies: emotion → Voice `:8090` → `blossom_audio` / `GET /v1/audio/{id}`
- Slim coding persona wrap + skip wrap when too big; ctx **16384**
- Web search uses `[USER REQUEST]`; skips useless search on editor dumps
- `blossom_intel_source` / labels → Local coder / Claude / Gemini in clients
- **`POST /v1/memory/coding`** / **`GET /v1/memory/coding?q=`** — coding lessons API
- Health: **`supports_memory_write`** / **`supports_voice`** / **`supports_feedback`**
- Multi-persona slots (`/v1/persona`, `/v1/personas`) with Companion UI
- `.gitignore`: `Mind/chromadb/`, `Mind/backups/`, `Mind/*.db`, `Voice/characters/**`, secrets

### Extension (Blossom Assistant) — companion to this stack

- Auto-apply / auto-save; path-labeled fences + headings
- `[LINK CHECK]` (EXISTS / MISSING) and `[UNUSED FILES]`
- Real file **delete** via Apply / Auto-apply
- Safe-delete mode: extension deletes orphans; skips model writes that recreate them or add unused links
- Summary card prefers **disk truth** over model “Deleted…” prose
- After **Gemini escalate**, POST lesson to ChatRouter (`source=blossom_assistant_gemini`)

### Chat UI (Blossom Companion)

- Streaming chat + thoughts; JA/EN locale toggle
- Personality panel: multi-slot personas, **voice pack** dropdown
- Plays / stops companion WAV from ChatRouter
- **Correct / Incorrect** on coding & Japanese-teaching replies (optional note); companion chat has no rating UI

---

## Routing today

- **Casual** → persona (+ web search if triggered); **no** correctness feedback
- **Coding** → pack editor context → **local coder ladder** + coding/web RAG → next local on uncertainty → Claude/Gemini per `CLOUD_FALLBACK_ORDER` if still needed → save useful answers → persona voice wrap (or skip wrap if too large) → optional user Correct/Incorrect
- **Japanese** → persona first (+ `language_lessons` RAG); cloud only if thin/failed → optional user Correct (gated learn) / Incorrect

**Learning** = RAG into Chroma (+ reflection updates SQLite metrics), **not** fine-tuning weights.

| Path | Learns into `coding_lessons`? |
|------|-------------------------------|
| Local coder success (ChatRouter) | Yes (`local_coder:<gguf-name>`) |
| Claude/Gemini via ChatRouter fallback | Yes (`claude` / `gemini`) |
| Extension Gemini escalate | Yes (`blossom_assistant_gemini`) |
| Extension Claude escalate | No UI yet (Claude-via-router already learns) |
| User marks coding **Correct** | Boost existing lesson (importance 9) or learn if missing |
| User marks coding **Incorrect** | Delete that auto-saved lesson; optional caution from note |

| Path | Learns into `language_lessons`? |
|------|--------------------------------|
| Japanese auto-reply | No (gated) |
| User marks Japanese **Correct** | Yes (`…+user_verified`) |
| User marks Japanese **Incorrect** + note | Caution only |
| Casual / companionship | Never (no `feedback_id`) |

Model / cloud order in `PythonScripts/.env`:

```env
# Preferred multi-coder ladder (or use CODER_MODEL_PATH + CODER_ALT_MODEL_PATH)
# CODER_MODELS=coding/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf,coding/DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf
CODER_ALT_MODEL_PATH=coding/DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf
CLOUD_FALLBACK_ORDER=gemini,claude
```

---

## Mental model

```
Client (Companion / Blossom Assist / any OpenAI client)
  → ChatRouter :8081
       ├─ SQLite (recent chat + persona book / voice_id + feedback_turns)
       ├─ Chroma (life / coding / language / web memories)
       ├─ Web search (optional)
       ├─ llama-server :11434 (persona XOR one coder GGUF; ladder swaps files)
       ├─ Claude / Gemini (after local ladder, order from env)
       └─ Voice :8090 (SBV2 / Edge → RVC → WAV) when VOICE_ENABLED
  → Disk Apply / Delete (extension only)
  → Optional Gemini escalate (extension) → POST /v1/memory/coding
  → Optional Correct/Incorrect (Companion) → POST /v1/feedback
```

---

## Roadblocks we hit

1. **Paths / layout** — Desktop → Documents; scripts use path-from-`__file__`.
2. **Wrong llama.cpp build** — needed Windows x64 CUDA 12 for RTX 4090.
3. **Space in path + PowerShell** — quoting mattered for `Start-Process`.
4. **MSYS2 `cmd` on PATH** — bare `cmd` opened “pick an app” dialogs.
5. **Trimmed runtime too hard** — deleting `mtmd.dll` broke the server; restored.
6. **VRAM** — persona + 30B coder can’t stay loaded → hot-swap; alt coder = another full reload; Voice needs its own CUDA stack.
7. **HF vs GGUF** — coding model must be GGUF for llama-server; `add-model.ps1` downloads GGUFs only.
8. **Persona wrap blew context** — huge editor dump + wrap → 400s; slim/skip wrap + pack + 16k ctx.
9. **CREATE vs EDIT** — model overwrote `index.html` instead of creating `about.html`.
10. **False “missing” / dead links** — removed EXISTS links; invented junk files.
11. **“Deleted” but file remained** — Summary claimed delete; Apply was write-only → real deletes + disk-truth Summary.
12. **Safe-delete flipped into creates** — model added unused links / recreated orphans → extension owns `[UNUSED FILES]`.
13. **Extension escalate didn’t learn** — Gemini called Google directly → memory HTTP API + hook.
14. **“Backend: Claude” vs “Gemini only”** — ChatRouter Claude fallback ≠ extension Gemini escalate (both real, different paths).
15. **Folder rename** — Cursor lock delayed `AI Girlfriend` → `Blossom`.
16. **Google search** — no free official Google API; DuckDuckGo default; Serper ≈ Google-quality.
17. **Voice pip / omegaconf** — `style-bert-vits2` pins old omegaconf; use dedicated `VOICE_PYTHON` venv + `pip<24.1` for that install.
18. **EN through JP-trained RVC** — sounded Japanese → separate Eng RVC packs + Edge→RVC path.
19. **Persona catchphrase loop** — voice/system nudges were too sticky → softened anti-intro prompts.
20. **SQLite `created_at` migrate** — `ADD COLUMN … DEFAULT CURRENT_TIMESTAMP` failed; plain `ADD COLUMN` instead.

---

## What we learned

- Disk truth beats model prose (exists / unused / deleted).
- Safe-delete ≠ dead-link cleanup (orphans vs MISSING hrefs).
- Fix the owner of the bug: filesystem → extension; routing/RAG → ChatRouter.
- Don’t fine-tune per language — fences + disk checks + RAG scale better.
- Backup Chroma by **copying** `Mind/chromadb` with ChatRouter stopped; also back up `CompanionMind.db` for short-term mind.
- RAG lesson text is truncated (useful patterns, not full repo dumps).
- Keep Voice weights under `Voice/characters/` so gitignore stays simple; discover packs, don’t hard-code paths in presets.
- Defer TTS until after text streams; heuristic emotion is enough for most replies.
- Correctness feedback ≠ “train the model”: boost/delete Chroma lessons only; never rate companionship (avoids freezing personality via reply remix).
- Japanese teaching: learn **only** on thumbs-up; don’t auto-save every study reply.
- **“Commit” learning** = backup `Mind/chromadb` + `CompanionMind.db` (RAG snapshot), not safetensors/GGUF weight merges.
- Fine-tune / LoRA would **not** beat RAG for lessons/facts (reversible Correct/Incorrect, situational knowledge); modest token savings vs editor context cost.
- LoRA later only for **stable always-on** style/skills (persona voice, PLAN→fences→Summary contract) — after modular inject + compress of `coding_rules.txt`, not as first token fix.
- Situational lessons stay in Chroma forever; plain-text guardrail bloat → conditional injection / shorter core / host enforcement first.

---

## What it can do right now

### Yes

- Local OpenAI-compatible chat on `:8081`
- Short-term SQLite + long-term Chroma recall
- Multi-persona book + timed self-reflection
- Coding path with local coder ladder (Qwen → DeepSeek) + cloud last resort + learn
- Add any local GGUF via `Brains/add-model.ps1` + env path / `CODER_MODELS`
- Web search + `web_knowledge`
- Streaming thoughts for UI progress
- Compact old history into life memory
- Editor context packing for large dumps
- Extension: multi-file Apply, link check, unused-file delete, Gemini → memory
- **Spoken replies** (optional): JA/EN pipelines, character packs, Companion playback
- Companion: locale toggle, persona settings, voice pack dropdown
- Correctness feedback (coding + Japanese teaching) → Chroma boost / gated language lessons

### Not yet (planned / discussed)

- Microphone / STT input (TTS output exists)
- Live2D / animated avatar
- Fine-tuning / LoRA for frozen always-on style/skills (not for Chroma lessons; see 2026-07-13 notes)
- Hardened public hosting (auth, tunnel, etc.)
- Native Google Custom Search
- Claude escalate UI inside the extension
- Correctness feedback buttons inside Blossom Assistant (API exists; Companion UI only for now)
- Multi-pass map-reduce over entire repos (single-pass pack only)

If GGUFs under `Brains/models/...` are missing, local persona/coder won’t run until those files exist.
If Voice packs under `Voice/characters/...` are missing, spoken replies won’t run until those files exist.

---

## Why we chose X over Y

| Choice | Why |
|--------|-----|
| llama.cpp over Ollama | GGUFs + CUDA binaries on hand; explicit ctx/GPU layers; hot-swap = process restart |
| FastAPI over Laravel | Thin Python glue next to mind scripts; OpenAI-compatible for any client |
| SQLite short-term | Ordered chat + metrics; one file under `Mind/` |
| Chroma long-term | Semantic recall; local; Python-native |
| Both SQLite + Chroma | Recent dialogue vs durable lessons; compactor moves old chats → Chroma |
| Hot-swap over two loaded models | One 4090 can’t hold persona + 30B + KV comfortably |
| Coder ladder over single coder | Second opinion when uncertain without burning cloud $ first |
| DeepSeek-Coder-V2-Lite as alt | Different lineage than Qwen; solid code; ~10GB Q4; run **local only** (avoids hosted DeepSeek privacy fuss) |
| Env + `add-model.ps1` over hard-coded models | Drop any GGUF; point `.env`; no ChatRouter fork per model |
| Cloud as last resort | Local-first; useful answers still land in Chroma |
| DuckDuckGo default search | No API key |
| RAG “learning” over fine-tune | Instant, reversible, cheap |
| Mind backups over weight “commits” | Chroma/SQLite snapshot = durable knowledge; LoRA only for stable always-on habits if prompt tax gets bad |
| Modular/compress rules before LoRA | `coding_rules.txt` always-on is ~1.5–3k tokens; editor context still dominates; inject by intent first |
| Correctness feedback only on coding + JP teaching | Objective right/wrong signal; companionship thumbs would remix preferred replies and poison dynamism |
| JP lessons gated on Correct | Auto-heuristic “useful” is weaker for language facts; wrong ✅ would stick |
| Extension owns deletes | Models lie about the filesystem |
| Shared Chroma via ChatRouter API | One mind; extension doesn’t run its own vector DB |
| Separate Voice service + characters/ | Heavy CUDA deps stay out of ChatRouter; gitignore packs in one folder |
| Discover packs + persona `voice_id` | Adding a character = drop folder + pick in UI |
| Edge→RVC for English | JP-trained RVC alone made EN speech sound Japanese |

---

## Ops cheatsheet

```powershell
# Restart ChatRouter + Voice (Python / .env / coding_rules / Voice code)
# Ctrl+C the running start-server.ps1, then:
& "C:\Users\Zepse\Documents\Blossom\start-server.ps1"

# Add / download a local GGUF (then set .env + restart)
cd Brains
.\add-model.ps1 -ListPresets
.\add-model.ps1 -Preset deepseek-coder-v2-lite
# .\add-model.ps1 -Role coding -Repo "owner/Some-GGUF" -File "Some-Q4_K_M.gguf"

# After Blossom Assistant compile
# Command Palette → Developer: Reload Window

# Backup Chroma (stop ChatRouter first)
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item -Recurse -Force `
  "C:\Users\Zepse\Documents\Blossom\Mind\chromadb" `
  "C:\Users\Zepse\Documents\Blossom\Mind\backups\chromadb-$stamp"

# Also consider backing up Mind\CompanionMind.db with it
```

Smoke checks:

```powershell
# ChatRouter may be on Tailscale IP — use the host from .env CHAT_ROUTER_HOST
curl -s http://XXX.XXX.XXX.XXX:8081/health
curl -s "http://XXX.XXX.XXX.XXX:8081/v1/memory/coding?q=unused%20file&n=3"
# After a coding/JP reply, use blossom_feedback.id from the completion / SSE:
# curl -s -X POST http://XXX.XXX.XXX.XXX:8081/v1/feedback -H "Content-Type: application/json" -d "{\"feedback_id\":\"…\",\"verdict\":\"correct\"}"
curl -s http://XXX.XXX.XXX.XXX:8081/v1/voices
curl -s http://127.0.0.1:8090/health
```

---

## Session log

Dated work notes (newest first). High-level “what’s built” stays above; this section is the changelog by sitting.

### Session — 2026-07-13

**Mind “commit” vs LoRA / safetensors** — 2026-07-13 evening (~20:02–20:13 ET)
- Question: can we “commit” what Blossom learned like image-gen LoRAs / safetensors?
- Finding: **no weight commit today.** Learning = Chroma + SQLite; “commit” = copy `Mind/chromadb` (+ `CompanionMind.db`) with ChatRouter stopped. GGUFs stay frozen.
- Fine-tune from experience: **not worth it soon** — weaker than RAG for lessons/facts; Correct/Incorrect stay reversible; token savings small vs editor dumps / history.
- When LoRA *would* make sense later: **stable style or skill set** baked for months (persona catchphrase bans / TTS style; always-on PLAN→path fences→CREATE vs EDIT→Summary). Not life facts, project lessons, or one-off Correct votes.
- Guardrail fear (plain-text rules grow → token tax): valid for always-on text. Sequence: **split/inject by intent → compress settled core → push enforcement to extension → only then LoRA** for the frozen slice. Keep a short prose contract for cloud/edge cases.
- Voice `.safetensors` (RVC) remain voice timbre only — not chat experience.

**Correctness feedback (coding + Japanese teaching)** — 2026-07-13 evening
- Decision: rate **correctness**, not companionship likes (avoids reply-template remix / freezing persona).
- `SemanticMemory.py`: `language_lessons` collection; importance-aware query; get/delete/update helpers; `learn_language_lesson`.
- `FeedbackStore.py`: SQLite `feedback_turns`; `POST` apply Correct → boost/learn, Incorrect → delete coding lesson (+ optional caution note); JP learn **only** on Correct.
- `ChatRouter.py`: issue `feedback_id` on coding/JP routes; JP injects `language_lessons` RAG; `POST /v1/feedback`; SSE `blossom.feedback`; health `supports_feedback`.
- Companion: Correct / Incorrect + optional note on feedbackable bubbles (sibling `Blossom Companion/`).
- `.env.example`: `CHROMA_COLLECTION_LANGUAGE`, `MEMORY_MIN_IMPORTANCE`.
- Restart ChatRouter + refresh Companion to pick up UI/API.

**Local coder ladder + agnostic model add** — 2026-07-13 evening (~19:40–20:00 ET)
- `LocalModels.py`: resolve paths under `Brains/models/` or absolute; `CODER_MODELS` / `CODER_ALT_MODEL_PATH` ladder.
- `LlamaServerManager`: load any coder GGUF path; track `active_model` (not just persona/coder role).
- `ChatRouter`: try next local coder on weak / escalate marker / incomplete multi-file, then cloud; learn source `local_coder:<name>`.
- `Brains/add-model.ps1` + `model-presets.json` + `download_local_model.py`; preset `deepseek-coder-v2-lite` (bartowski Q4_K_M).
- Downloaded DeepSeek-Coder-V2-Lite-Instruct into `Brains/models/coding/` (2026-07-13 ~19:46 ET); `.env` set `CODER_ALT_MODEL_PATH=coding/DeepSeek-….gguf`.
- Docs: `Brains/README.md`, `.env.example`; `/health` exposes `coder_ladder` / `coder_ladder_available`.
- PowerShell: args **outside** quotes — `& "…\add-model.ps1" -Preset deepseek-coder-v2-lite`.
- Restart `start-server.ps1` after env / new GGUF so the ladder is live.

**History compaction** — 2026-07-13
- Compactor was running *before* llama-server existed → connect timeout to `:11434` (not Tailscale).
- Moved compaction into ChatRouter lifespan after persona llama is ready; removed early compact from `start-server.ps1`.
- `COMPACT_ON_STARTUP` (default true). Compaction still can 400 on huge stale batches (logged; logs preserved).

**Repo hygiene** — 2026-07-13
- `.gitignore`: `*.log`; `Voice/characters/**` (keep `characters/README.md`).

**English voice tuning** — 2026-07-13
- EN-only `pitch_en` + `english.pitch_offset` (JA pitches unchanged).
- Edge base: Jenny → Ana → Emma → **AvaNeural**; settled with Ava + pitch_offset 1.
- EN `index_rate` 0.12; happy `pitch_en` 6.
- Faster EN: `english.f0method: pm`, higher Edge rates, `VOICE_MAX_CHARS=180`.

**Speech sanitization** — 2026-07-13
- Strip emojis before TTS (no “rocket”).
- Strip markdown `*emphasis*` / `**bold**` / stray `*_`` so TTS doesn’t say “asterisk”.
- Voice nudges: prefer no emoji in replies when voice is on.

**Emotion heuristics** — 2026-07-13
- Expanded English keyword coverage for clearer cues.
- **`neutral` is speakable** (presets + SPEAK_EMOTIONS); default unmatched → `VOICE_DEFAULT_EMOTION=neutral` (was skip / force-happy).

**Persona catchphrase loop** — 2026-07-13
- Root cause: history few-shots sticky `*Snaps fingers*` + “Don't make me regret… tracker” (not just notes).
- Hardened motif bans + history sanitization for generation prompts; post-pass strips sticky opener/closer before log/UI.
- Updated VOICE `personality_notes` with explicit tracker / snaps-fingers bans.
- Remix fix: one-noun template swaps (sleeping-power → dog) caught via overlap check + one-shot rewrite; anti-echo no longer pastes full prior replies.

**Speed / “smart + fast”** — 2026-07-13
- Explained: Ubuntu headless ≠ big GPU speedup on a 4090; RAM pressure matters more.
- **Persona CoT off by default:** `PERSONA_REASONING=off`, `--reasoning-budget 0`, flash-attn on (`LlamaServerManager`).
- Coder keeps `CODER_REASONING=auto`.
- Plan: Qwen3-**14B** Q4_K_M + no CoT for smarter chat without long thinking tax; user started `hf download bartowski/Qwen_Qwen3-14B-GGUF …`.

**Ops note** — 2026-07-13
- ChatRouter binds Tailscale `XXX.XXX.XXX.XXX:8081`; Voice stays `127.0.0.1:8090`. Companion must hit Tailscale URL.

---

### Session — 2026-07-12

**Multi-character voice packs** — 2026-07-12
- Auto-discover `Voice/characters/<voice_id>/{Jpn,Eng}/` via `voices.py`.
- `POST /v1/speak` accepts `voice_id`; `GET /v1/voices` (+ ChatRouter proxy).
- Persona profile field `voice_id`; Companion Personality → voice pack dropdown.
- `presets.yaml` shared knobs + `default_voice` only (no hard-coded RVC paths).
- Lazy RVC load per `(voice_id, locale)`; SBV2 warm once.

**Layout / gitignore** — 2026-07-12
- `VOICE_CHARACTERS_DIR` override; tracked `characters/README.md`.

**Docs** — 2026-07-12
- Root `README.md`, `Voice/README.md`, `PROGRESS.md` updated for Voice + Companion.

**Cloud spend / reliability** — 2026-07-12
- Tightened cloud fallback to cut Claude spend on routine tasks.
- Memory API, model reasoning surface, server reliability improvements.
- First tracked git commit.

**Pipelines (unchanged core)** — 2026-07-12
- JA: Style-Bert-VITS2 → RVC  
- EN: Edge TTS → character Eng RVC  

---

*Last updated: 2026-07-13 — mind commit vs LoRA decision; correctness feedback; local coder ladder + DeepSeek alt.*
