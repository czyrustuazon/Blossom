# Blossom — progress & status

Local-first personal companion stack. **Not** a fine-tuned foundation model.

This document is the running “where we are” note for the Blossom backend (`Documents\Blossom`). The VS Code client lives in a sibling folder: `Documents\Blossom Assistant`.

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
  Brains/runtime/          # llama-server + CUDA DLLs
  Brains/models/...        # conversational + coding GGUFs
  Mind/                    # CompanionMind.db, chromadb/, pid/logs, backups/
  PythonScripts/           # ChatRouter, MemoryUpdater, SemanticMemory, …
  start-server.ps1
```

Sibling: `Blossom Assistant/` — VS Code extension (Apply, editor context, auto-apply, memory POST after Gemini escalate).

---

## What we’ve built

### Backend pieces

| Piece | Role |
|--------|------|
| `Brains/runtime/` | Trimmed CUDA 12 llama.cpp Windows binaries |
| `Brains/models/` | Conversational + coding GGUF slots |
| `Mind/` | SQLite mind, Chroma store, llama pid/role/logs |
| `MemoryUpdater.py` | SQLite mind, persona prompt, reflection every N turns |
| `SemanticMemory.py` | Chroma: `relationship_life`, `coding_lessons`, `web_knowledge` |
| `HistoryCompactor.py` | Old SQLite chats → life memories, prune/VACUUM |
| `LlamaServerManager.py` | Hot-swap persona ↔ coder on one GPU |
| `ChatRouter.py` | Route casual / coding / Japanese; thoughts SSE; cloud fallback; learn |
| `WebSearch.py` | DuckDuckGo / Brave / Serper / Bing → inject + store |
| `EditorContext.py` | Select → chunk → rank → pack for coder budget |
| `coding_rules.txt` | PLAN→EXECUTE→VERIFY, CREATE vs EDIT, fences, link/orphan rules |
| `.env` / `.env.example` | Keys, models, collections, search, `CLOUD_FALLBACK_ORDER` |

### Newer backend work

- Slim coding persona wrap + skip wrap when too big; ctx **16384**
- Web search uses `[USER REQUEST]`; skips useless search on editor dumps
- `blossom_intel_source` / labels → Local coder / Claude / Gemini in clients
- **`POST /v1/memory/coding`** — extension (or curl) writes coding lessons
- **`GET /v1/memory/coding?q=`** — search/verify lessons
- Health flag **`supports_memory_write`**
- `.gitignore`: `Mind/chromadb/`, `Mind/backups/`, `Mind/*.db`, secrets

### Extension (Blossom Assistant) — companion to this stack

- Auto-apply / auto-save; path-labeled fences + headings
- `[LINK CHECK]` (EXISTS / MISSING) and `[UNUSED FILES]`
- Real file **delete** via Apply / Auto-apply
- Safe-delete mode: extension deletes orphans; skips model writes that recreate them or add unused links
- Summary card prefers **disk truth** over model “Deleted…” prose
- After **Gemini escalate**, POST lesson to ChatRouter (`source=blossom_assistant_gemini`)

---

## Routing today

- **Casual** → persona (+ web search if triggered)
- **Coding** → pack editor context → local coder + coding/web RAG → Claude then Gemini per `CLOUD_FALLBACK_ORDER` if needed → save useful answers → persona voice wrap (or skip wrap if too large)
- **Japanese** → persona first; cloud only if thin/failed

**Learning** = RAG into Chroma (+ reflection updates SQLite metrics), **not** fine-tuning weights.

| Path | Learns into `coding_lessons`? |
|------|-------------------------------|
| Local coder success (ChatRouter) | Yes (`local_coder`) |
| Claude/Gemini via ChatRouter fallback | Yes (`claude` / `gemini`) |
| Extension Gemini escalate | Yes (`blossom_assistant_gemini`) |
| Extension Claude escalate | No UI yet (Claude-via-router already learns) |

Cloud order is set in `PythonScripts/.env`:

```env
CLOUD_FALLBACK_ORDER=claude,gemini
```

---

## Mental model

```
Client (Blossom Assist / any OpenAI client)
  → ChatRouter :8081
       ├─ SQLite (recent chat + personality metrics)
       ├─ Chroma (life / coding / web memories)
       ├─ Web search (optional)
       ├─ llama-server :11434 (persona XOR coder)
       └─ Claude / Gemini (last resort, order from env)
  → Disk Apply / Delete (extension only)
  → Optional Gemini escalate (extension) → POST /v1/memory/coding
```

---

## Roadblocks we hit

1. **Paths / layout** — Desktop → Documents; scripts use path-from-`__file__`.
2. **Wrong llama.cpp build** — needed Windows x64 CUDA 12 for RTX 4090.
3. **Space in path + PowerShell** — quoting mattered for `Start-Process`.
4. **MSYS2 `cmd` on PATH** — bare `cmd` opened “pick an app” dialogs.
5. **Trimmed runtime too hard** — deleting `mtmd.dll` broke the server; restored.
6. **VRAM** — persona + 30B coder can’t stay loaded → hot-swap.
7. **HF vs GGUF** — coding model must be GGUF for llama-server.
8. **Persona wrap blew context** — huge editor dump + wrap → 400s; slim/skip wrap + pack + 16k ctx.
9. **CREATE vs EDIT** — model overwrote `index.html` instead of creating `about.html`.
10. **False “missing” / dead links** — removed EXISTS links; invented junk files.
11. **“Deleted” but file remained** — Summary claimed delete; Apply was write-only → real deletes + disk-truth Summary.
12. **Safe-delete flipped into creates** — model added unused links / recreated orphans → extension owns `[UNUSED FILES]`.
13. **Extension escalate didn’t learn** — Gemini called Google directly → memory HTTP API + hook.
14. **“Backend: Claude” vs “Gemini only”** — ChatRouter Claude fallback ≠ extension Gemini escalate (both real, different paths).
15. **Folder rename** — Cursor lock delayed `AI Girlfriend` → `Blossom`.
16. **Google search** — no free official Google API; DuckDuckGo default; Serper ≈ Google-quality.

---

## What we learned

- Disk truth beats model prose (exists / unused / deleted).
- Safe-delete ≠ dead-link cleanup (orphans vs MISSING hrefs).
- Fix the owner of the bug: filesystem → extension; routing/RAG → ChatRouter.
- Don’t fine-tune per language — fences + disk checks + RAG scale better.
- Backup Chroma by **copying** `Mind/chromadb` with ChatRouter stopped; also back up `CompanionMind.db` for short-term mind.
- RAG lesson text is truncated (useful patterns, not full repo dumps).

---

## What it can do right now

### Yes

- Local OpenAI-compatible chat on `:8081`
- Short-term SQLite + long-term Chroma recall
- Personality evolution via timed self-reflection
- Coding path with local coder + cloud last resort + learn
- Web search + `web_knowledge`
- Streaming thoughts for UI progress
- Compact old history into life memory
- Editor context packing for large dumps
- Extension: multi-file Apply, link check, unused-file delete, Gemini → memory

### Not yet (planned / discussed)

- Voice I/O, Live2D / animated avatar
- Multi-character “persona packs” as a product
- Fine-tuning / weight updates from experience
- Hardened public hosting (auth, tunnel, etc.)
- Native Google Custom Search
- Claude escalate UI inside the extension
- Multi-pass map-reduce over entire repos (single-pass pack only)

If GGUFs under `Brains/models/...` are missing, local persona/coder won’t run until those files exist.

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
| Cloud as last resort | Local-first; useful answers still land in Chroma |
| DuckDuckGo default search | No API key |
| RAG “learning” over fine-tune | Instant, reversible, cheap |
| Extension owns deletes | Models lie about the filesystem |
| Shared Chroma via ChatRouter API | One mind; extension doesn’t run its own vector DB |

---

## Ops cheatsheet

```powershell
# Restart ChatRouter (Python / .env / coding_rules changes)
# Ctrl+C the running start-server.ps1, then:
& "C:\Users\Zepse\Documents\Blossom\start-server.ps1"

# After Blossom Assistant compile
# Command Palette → Developer: Reload Window

# Backup Chroma (stop ChatRouter first)
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item -Recurse -Force `
  "C:\Users\Zepse\Documents\Blossom\Mind\chromadb" `
  "C:\Users\Zepse\Documents\Blossom\Mind\backups\chromadb-$stamp"

# Also consider backing up Mind\CompanionMind.db with it
```

Memory smoke checks:

```powershell
curl -s http://127.0.0.1:8081/health
curl -s "http://127.0.0.1:8081/v1/memory/coding?q=unused%20file&n=3"
```

---

*Last updated: 2026-07-12 — status snapshot for handoff / “where we’re at.”*
