# Blossom — Must Do

Action items for **Cursor Agent escalation**, **cost-aware complement workflow**, and **long-term coding improvement**.

**Last updated: 2026-08-02** (P0–P4 shipped; **P5** NLPP seeds; **P6** LoRA pipeline; **P7** README migration)

This document is the **implementation spec** for the next engineer or LLM agent. Read `PROGRESS.md` for historical status; read **§ LLM agent onboarding prompt** at the bottom for a copy-paste briefing.

**Shipped in Blossom Assistant (2026-08-02):** P0 `copyCursorHandoff`, P1 `ESCALATE_CURSOR` + SDK + shared compression + Cursor→Gemini fallback, **P2-deescalate** `Retry with local Blossom`, **P3** cloud → Apply cards (`blossom.escalate.applyFromCloud`). **Shipped in ChatRouter (2026-08-02):** **P2** cloud handoff compression before `_cloud_facts()`. **Shipped in Blossom repo:** **P4** eval harness + startup eval, **P5** NLPP lesson seeds, **P6** LoRA export/train pipeline, **P7** README migration. Learning on escalate answers uses **👍/👎** (not auto-learn or clipboard import).

---

## Table of contents

1. [Executive summary](#executive-summary)
2. [Vision & viability assessment](#vision--viability-assessment)
3. [Multi-repo layout](#multi-repo-layout)
4. [System architecture](#system-architecture)
5. [What works today (detailed)](#what-works-today-detailed)
6. [The gap: Cursor Agent escalation](#the-gap-cursor-agent-escalation)
7. [Must do #1 — Cursor escalate (full spec)](#must-do-1--cursor-escalate-full-spec)
8. [Must do #1b — Image upload & vision routing](#must-do-1b--image-upload--vision-routing)
9. [Must do #1c — Context interrupt & continue (Blossom Assistant)](#must-do-1c--context-interrupt--continue-blossom-assistant)
10. [Must do #2 — Manual handoff (P0)](#must-do-2--manual-handoff-p0)
11. [Must do #3 — Cost / routing playbook](#must-do-3--cost--routing-playbook)
12. [Must do #4 — Improve coding over time](#must-do-4--improve-coding-over-time)
13. [Must do #5 — ChatRouter alignment (optional)](#must-do-5--chatrouter-alignment-optional)
14. [Must do #6 — Docs & README migration (required)](#must-do-6--docs--readme-migration-required)
15. [API reference](#api-reference)
16. [Testing checklist](#testing-checklist)
17. [Try later (manual verification)](#try-later-manual-verification)
18. [Anti-patterns (do not do)](#anti-patterns-do-not-do)
19. [Implementation order](#implementation-order)
20. [Open questions](#open-questions)
21. [LLM agent onboarding prompt](#llm-agent-onboarding-prompt)

---

## Executive summary

**User goal:** Blossom (local Qwen 30B + DeepSeek ladder) handles routine coding cheaply. When uncertain, it **escalates to Cursor Agent** (full tools: terminal, MCP, Ghidra, repo index). Cursor’s answer is **saved into Chroma** so future local runs retrieve it via RAG. This is **not** automatic weight training — it is memory + feedback first, LoRA later if needed.

**Primary deliverable:** Implement `ESCALATE_CURSOR` in **Blossom Assistant** by cloning the existing **Gemini escalate** pattern and calling the **Cursor SDK** (`@cursor/sdk`).

**Secondary deliverable (P0, shipped):** Manual handoff — `copyCursorHandoff` copies compressed session to clipboard for Cursor IDE. Learning uses **👍/👎** on the reply (not clipboard import).

**Next UX deliverable (P1c-interrupt):** Let the user **inject more context mid-turn** while the agent is busy, then **continue** the tool loop with that new information — without requiring Stop + full re-ask. See [Must do #1c](#must-do-1c--context-interrupt--continue-blossom-assistant).

**Strategic verdict:** This is **not a pipe dream** if scoped as a **tiered hybrid stack** (local cheap → escalate hard → learn via RAG). It **is** a pipe dream if the goal is “local eventually replaces Cursor entirely.” See [Vision & viability assessment](#vision--viability-assessment).

**Documentation requirement:** When P0/P1 are implemented, **migrate** the vision, routing playbook, and escalation setup from this file into **`README.md`** (see [Must do #6](#must-do-6--docs--readme-migration-required)). `MustDo.md` stays the working spec; `README.md` becomes the user-facing source of truth.

---

## Vision & viability assessment

*Captured 2026-08-02 — documents why this project has merit, what to avoid, and the planned 70B hardware upgrade path.*

### North star (what we are building)

A **cost-aware hybrid intelligence stack**, not a single local model that outgrows Cursor:

```
Today (RTX 4090, 24 GB VRAM):
  Blossom 30B MoE + DeepSeek  →  routine coding cheaply (Blossom Assistant)
  Cursor Agent                →  hard RE, Ghidra MCP, long multi-tool sessions
  Chroma RAG                  →  remembers what Cursor / cloud taught

Future (70B-capable hardware — when funded):
  Blossom 70B-class coder     →  fewer cloud + Cursor escalations
  Cursor Agent                →  still the top tier for nasty RE / agent work
  Optional LoRA               →  stable output habits only (fences, Apply protocol)
```

### Verdict table

| Claim | Verdict | Notes |
|-------|---------|-------|
| Local Qwen 30B + DeepSeek for daily coding | **Merit** | Already running; ladder validated in production |
| Gemini → Claude as text-only cloud fallback | **Merit** | `CLOUD_FALLBACK_ORDER=gemini,claude`; keep `CLOUD_ESCALATE_ON_INCOMPLETE=false` |
| Learn successes into Chroma (RAG) | **Merit** | Best ROI; reversible via Correct/Incorrect |
| Escalate to Cursor when stuck (tools/MCP) | **Merit** | Right tool for hard tier — MustDo #1 |
| Save money vs Cursor-only workflow | **Merit** | Only if Blossom owns the ~70% routine slice |
| Upgrade to **70B coder** when hardware allows | **Merit** | Requires **full-GPU residency**, not CPU spill on 4090 |
| Blossom **fully replaces** Cursor Agent | **Pipe dream** | Agent loop, MCP, indexing stay valuable on hard tasks |
| RAG alone = “training the model weights” | **Pipe dream** (wording) | RAG = **system** learning; LoRA is a separate later phase |
| Zero cloud / agent cost forever | **Pipe dream** | Cursor + occasional Gemini/Claude remain in budget |
| 72B hybrid on single 4090 with CPU spill | **Rejected** | Measured ~0.35 tok/s — documented in `PROGRESS.md` |

### What already proves merit (not vaporware)

1. **ChatRouter** — OpenAI-compatible router, coder ladder, cloud fallback, learn API
2. **Blossom Assistant** — agent loop, Apply/delete disk truth, Gemini escalate + learn
3. **Empirical 72B rejection** — tried Qwen2.5-72B Q3_K_M with GPU spill; unusable speed → ladder restored to 30B MoE + DeepSeek
4. **Eval corpus** — `blossom-php-modernization-training-set` for measurable improvement
5. **Documented learning model** — RAG first, LoRA later for frozen habits only (`PROGRESS.md`)

### Where the vision fails if mis-scoped

1. **“Local will eventually replace Cursor”** — Even 70B improves answer quality, not agent toolchain parity (Ghidra MCP, integrated terminal, repo index in the IDE you use for NLPP).
2. **“Chroma trains the GGUF”** — Weights unchanged until explicit LoRA/export; similar future tasks improve when lessons **retrieve well**, not by magic generalization.
3. **“One IDE for everything”** — Blossom Assistant (VS Code) + Cursor (NLPP) + Companion is real overhead; each tool must own a **lane**.
4. **“70B on current 4090”** — Same box with CPU spill already failed; 70B is a **hardware milestone**, not a settings change.

### 70B upgrade plan (future — when funded)

**Goal:** Run a 70B-class **coder** fully on GPU at interactive speed (target: usable tok/s for Assistant streams, not ~0.35 tok/s).

**Do not repeat:** Qwen2.5-72B Q3_K_M with `CODER_N_GPU_LAYERS` spill to CPU/RAM on 24 GB — rejected 2026-07-26.

**Hardware targets (realistic):**

| Setup | 70B interactive coder? | Notes |
|-------|------------------------|-------|
| Single RTX 4090 (24 GB) + CPU spill | **No** | Already measured; keep 30B MoE primary |
| Single 48 GB GPU (RTX 6000 Ada, A6000 48GB) | **Maybe** | Q4 tight; Q3_K_M plausible with tuned ctx |
| Dual 24 GB (2×4090, tensor split) | **Yes** | Common llama.cpp path |
| Dedicated inference box 64–128 GB VRAM | **Yes** | Comfortable headroom |
| Apple Silicon 128+ GB unified memory | **Yes** | For llama.cpp/Ollama-style serving |

**Software steps when hardware lands:**

1. Download 70B-class coder GGUF via `Brains/add-model.ps1` (e.g. preset `qwen25-72b` or successor Qwen3-Coder dense).
2. Set `CODER_MODELS` with 70B primary; keep 30B MoE or DeepSeek as fast fallback if desired.
3. Tune `CODER_N_GPU_LAYERS=999`, `CODER_CTX_SIZE` (start 8192–16384), verify tok/s in `/health` + manual stream test.
4. Re-benchmark: routine coding pass rate, escalation rate to Cursor/Gemini, tok/s floor for UX.
5. Update `README.md` hardware section (per MustDo #6).

**Priority rule:** **Full-GPU residency beats parameter count.** A fast 30B MoE entirely on GPU beats a crawling 70B hybrid. Upgrade hardware before upgrading parameters on a spill config.

### Expected outcomes by phase

| Phase | Escalation rate | Cost profile |
|-------|-----------------|--------------|
| Now (30B + Cursor complement) | Cursor on hard ~10–30% | Low local + bounded Cursor |
| After P0/P1 (Cursor SDK escalate + learn) | Same tasks, smoother handoff | Lessons reduce repeat escalations |
| After 70B + proper HW | Fewer Cursor/Gemini escalations | Higher upfront HW; lower marginal API $ |
| After LoRA (optional, deferred) | Slightly fewer format retries | GPU time once; not per-token |

### Anti-goals (explicit)

- Replace Cursor for NLPP reverse-engineering entirely
- Fine-tune GGUF from every Chroma lesson automatically
- Tunnel Cursor Override URL → ChatRouter as the main architecture
- Re-enable 72B hybrid on 4090 “because 70B sounds better”

---

## Multi-repo layout

All paths relative to `C:\Users\Zepse\Documents\` unless noted.

| Repo | Path | Role |
|------|------|------|
| **Blossom** | `Blossom\` | ChatRouter FastAPI `:8081`, llama-server hot-swap, Chroma, SQLite mind |
| **Blossom Assistant** | `Blossom Assistant\` | VS Code extension — agent loop, Apply/delete, Gemini escalate |
| **Blossom Companion** | `Blossom Companion\` | Nuxt chat UI, personas, voice, Correct/Incorrect thumbs |
| **Eval corpus** | `blossom-php-modernization-training-set\` | Benchmark for modernization evals (not LoRA data yet) |
| **NLPP (example domain)** | `New Love Plus Decompilation\NewLovePlusPlusEngPatcher\` | User’s romhack project — source of domain-specific lessons |

**Start Blossom backend:**

```powershell
& "C:\Users\Zepse\Documents\Blossom\start-server.ps1"
# Health: http://127.0.0.1:8081/health
```

**Build Blossom Assistant:**

```powershell
cd "C:\Users\Zepse\Documents\Blossom Assistant"
npm install && npm run compile
# F5 in VS Code to debug extension
```

---

## System architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  VS Code — Blossom Assistant extension                                   │
│  ├─ ChatPanel (UI)                                                       │
│  ├─ orchestrator.ts — agent tool loop, Apply, escalate hooks             │
│  ├─ prompts.ts — CODING_AGENT_PROMPT, ESCALATE_GEMINI contract           │
│  ├─ gemini/escalate.ts — confirm → call Gemini → learn (DONE)            │
│  ├─ cursor/escalate.ts — confirm → Cursor SDK → learn (NOT BUILT)        │
│  ├─ memory/client.ts — POST /v1/memory/coding                            │
│  └─ feedback/client.ts — POST /v1/feedback (Correct/Incorrect)           │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ HTTP OpenAI-compatible
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  ChatRouter.py — FastAPI :8081                                           │
│  ├─ Route: casual → persona GGUF                                         │
│  ├─ Route: coding → pack editor context → coder ladder → cloud           │
│  ├─ Route: japanese → persona + language_lessons RAG                     │
│  ├─ SemanticMemory.py — Chroma collections                               │
│  ├─ LlamaServerManager.py — hot-swap persona ↔ one coder on GPU           │
│  └─ POST /v1/memory/coding, POST /v1/feedback, GET /health               │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ local OpenAI API
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  llama-server :11434 (CUDA, Brains/runtime/)                             │
│  One GGUF loaded at a time: persona XOR coder from Brains/models/        │
└─────────────────────────────────────────────────────────────────────────┘

Escalation targets (coding uncertainty):
  1. Next local coder in CODER_MODELS ladder
  2. ChatRouter cloud (Gemini → Claude) via CLOUD_FALLBACK_ORDER
  3. Extension Gemini escalate (ESCALATE_GEMINI) — text only, user confirms
  4. [PLANNED] Extension Cursor escalate (ESCALATE_CURSOR) — agent + tools
```

### Hardware assumptions (user machine)

- **GPU:** RTX 4090 class (~24 GB VRAM)
- **Persona:** Qwen3-14B Q4_K_M (conversational)
- **Primary coder:** Qwen3-Coder-30B-A3B-Instruct Q4_K_M (MoE, fits VRAM)
- **Alt coder:** DeepSeek-Coder-V2-Lite-Instruct Q4_K_M (~10 GB)
- **Rejected:** Qwen2.5-72B hybrid with CPU spill (~0.35 tok/s — unusable)

Persona and coder **cannot stay loaded together** — `LlamaServerManager` hot-swaps (seconds per switch).

---

## What works today (detailed)

### Local coder ladder (ChatRouter)

**File:** `Blossom/PythonScripts/LocalModels.py` — `coder_ladder()` reads `CODER_MODELS` env.

**File:** `Blossom/PythonScripts/ChatRouter.py` — `_get_coding_intel()` iterates ladder:

1. `server_manager.ensure("coder", model_path=…)` — load GGUF
2. `_local_coder_answer()` — infer with RAG from `coding_lessons` + `web_knowledge`
3. On weak answer / `ESCALATE_CLOUD` / incomplete heuristics → next local coder
4. Exhausted locals → `_cloud_facts()` per `CLOUD_FALLBACK_ORDER`
5. Success → `learn_coding_lesson(..., source=provider)`

**Env (`PythonScripts/.env`):**

```env
CODER_MODELS=coding/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf,coding/DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf
CLOUD_FALLBACK_ORDER=gemini,claude
CLOUD_FALLBACK_ENABLED=true
CLOUD_ESCALATE_ON_INCOMPLETE=false   # IMPORTANT: saves Claude $ — keep false
CLOUD_ESCALATE_ON_REQUEST=true
GEMINI_MODEL=gemini-2.5-flash-lite
CLAUDE_MODEL=claude-sonnet-4-5
```

**ChatRouter coder prompt rules:** `PythonScripts/coding_rules.txt` — uses `ESCALATE_CLOUD:` (backend path). Extension uses separate `ESCALATE_GEMINI:` (extension path).

### Extension Gemini escalate (reference implementation)

This is the **template to clone** for Cursor.

| Step | File | What happens |
|------|------|--------------|
| 1 | `src/agent/prompts.ts` | `CODING_AGENT_PROMPT` tells model to emit `ESCALATE_GEMINI: <reason>` |
| 2 | `src/agent/prompts.ts` | `stripEscalateMarker()` regex-strips marker, returns `escalateReason` |
| 3 | `src/agent/orchestrator.ts` ~726 | After model reply, if `escalateReason`, call `escalateToGemini()` |
| 4 | `src/gemini/escalate.ts` | Modal confirm with spend estimate → `callGemini()` |
| 5 | `src/gemini/client.ts` | Direct Google Generative Language API (not ChatRouter) |
| 6 | `src/memory/client.ts` | `learnCodingLesson({ source: "blossom_assistant_gemini" })` |
| 7 | `src/gemini/spend.ts` | Local JSON spend tracker in extension globalStorage |

**Handoff prompt builder** (`orchestrator.ts` `buildEscalatePrompt`):

```typescript
// Includes: user request, local attempt, last ~6 history turns
return [
  "The local coding assistant is stuck and the user approved a Gemini escalation.",
  `User request:\n${userText}`,
  `Local attempt:\n${localAttempt || "(empty)"}`,
  `Recent conversation:\n${recent}`,
  "Provide a clear, actionable answer. If code edits are needed, show full file contents or precise patches.",
].join("\n\n");
```

**For Cursor escalate:** Change preamble to mention Cursor Agent, include workspace root path, active file, repo knowledge snippet, and any tool errors from the local attempt.

### Learning model (RAG, not weights)

**Collection:** `coding_lessons` in `Mind/chromadb/` (gitignored).

**Write path:** `SemanticMemory.learn_coding_lesson()` — truncates to ~500 char ask + ~4000 char answer; skips if `looks_useful_answer()` fails.

**Sources already used:**

| `source` value | Origin |
|----------------|--------|
| `local_coder:<gguf-name>` | ChatRouter local success |
| `gemini` / `claude` | ChatRouter cloud fallback |
| `blossom_assistant_gemini` | Extension Gemini escalate |
| `extension` | Generic client default |
| `blossom_assistant_cursor` | **PLANNED** |
| `blossom_assistant_claude` | **PLANNED** (P1c extension Claude escalate) |
| `cursor_manual` | **PLANNED** manual import |

**Feedback loop** (`FeedbackStore.py` + `POST /v1/feedback`):

- **Correct** → boost lesson importance to 9, or learn if missing
- **Incorrect** → delete auto-saved lesson for that turn; optional caution note

**Important:** Correctness feedback does **not** update GGUF weights. It curates Chroma.

---

## The gap: Cursor Agent escalation

| Target | Tools (shell, MCP, Ghidra) | Vision / images | Auto-learn | User confirm | Status |
|--------|------------------------------|-----------------|------------|--------------|--------|
| ChatRouter local (Qwen/DeepSeek) | No | **No** — text GGUF only | Yes | No | Done |
| ChatRouter Gemini/Claude | No | Limited (text API) | Yes | No (automatic after ladder) | Done |
| Extension Gemini | No | Gemini multimodal if wired | Yes | Yes (modal) | Done |
| **Extension Cursor SDK** | **Planned** | **Planned** (file read + MCP) | **Planned** | **Yes (modal)** | **Not built** |
| Cursor IDE (direct) | Yes | Yes (chat attach + Read tool) | Manual import | N/A | Available today |

**Why Cursor ≠ Gemini:** Gemini escalate is a **single text completion**. Cursor Agent runs a **multi-step tool loop** against the real workspace — the same capability the user wants for NLPP reverse-engineering, Ghidra MCP, deploy scripts, etc.

**Why local Qwen cannot “see” uploads:** `Qwen3-Coder-30B-A3B-Instruct` GGUF in this stack is a **text coder** — no vision projector (`mmproj`), no image tensors to ChatRouter. Pasting or attaching PNGs to Blossom Assistant today would not reach the model as visual input even if the UI accepted files.

**Why not point Cursor Override URL at ChatRouter:** Cursor would lose Blossom’s RAG injection, editor packing, Apply protocol, and feedback UI while still consuming Cursor subscription tokens. Wrong direction for this goal.

---

## Must do #1 — Cursor escalate (full spec)

**Owner repo:** `Blossom Assistant` only (Cursor SDK needs VS Code workspace `cwd` and extension context).

### 1.1 New files to create

```
Blossom Assistant/src/escalate/
  compressHandoff.ts   — shared session compress/summarize (ALL cloud escalations)
  buildCloudHandoff.ts — one prompt builder; provider-specific preamble only
  fallbackChain.ts     — Cursor → Gemini → Claude with reused compression cache

Blossom Assistant/src/cursor/
  client.ts
  escalate.ts
  handoff.ts           — P0 manual copy/paste
  spend.ts

Blossom Assistant/src/claude/
  client.ts            — P1c Anthropic API (mirror gemini/client.ts)
  escalate.ts            — P1c same compressed handoff as Gemini/Cursor
  spend.ts               — optional
```

**Rule:** `compressConversationForHandoff()` is **one shared function** — never duplicate compression logic per provider.

### 1.2 Files to modify

| File | Changes |
|------|---------|
| `src/agent/prompts.ts` | Add `ESCALATE_CURSOR:`; extend `stripEscalateMarkers` for Cursor + Gemini |
| `src/agent/orchestrator.ts` | Cursor escalate + **refactor Gemini to shared compress** + optional fallback chain |
| `src/gemini/escalate.ts` | **Replace** `buildEscalatePrompt` last-6-turns with `buildCloudHandoffPrompt({ provider: "gemini" })` |
| `src/claude/escalate.ts` | **New P1c** — Claude with same compressed handoff |
| `src/config.ts` | Cursor + Claude secrets; **`blossom.handoff.*`** shared compression settings |
| `package.json` | Settings, commands, `@cursor/sdk` dependency |
| `src/extension.ts` | Register Cursor + Claude key commands |

### 1.3 Prompt contract (extension-side)

Add to `CODING_AGENT_PROMPT` in `prompts.ts` under ESCALATION section:

```text
If the task needs deep reverse-engineering, MCP/Ghidra, multi-step shell work,
or your local attempt failed after tools/context, say:

ESCALATE_CURSOR: <one-sentence reason>

If you only need a smarter text model (no tools), say:

ESCALATE_GEMINI: <one-sentence reason>

Do not escalate for trivial fixes the local model can finish.
Do not emit both markers in one reply — pick the smallest sufficient escalation.
```

**Decision rule for orchestrator:**

- `ESCALATE_CURSOR` → Cursor SDK path (agent + tools)
- `ESCALATE_GEMINI` → existing Gemini path (text only)
- If user disabled Cursor (`blossom.cursor.enabled=false`), show notice and offer Gemini fallback

### 1.4 `stripEscalateMarkers` — suggested implementation

```typescript
export type EscalateTarget = "gemini" | "cursor";

export function stripEscalateMarkers(text: string): {
  clean: string;
  target?: EscalateTarget;
  escalateReason?: string;
} {
  const cursor = text.match(/ESCALATE_CURSOR:\s*(.+)/i);
  const gemini = text.match(/ESCALATE_GEMINI:\s*(.+)/i);
  const pick = cursor ?? gemini;
  if (!pick) return { clean: text };
  const target: EscalateTarget = cursor ? "cursor" : "gemini";
  let clean = text
    .replace(/\n?ESCALATE_CURSOR:\s*.+/i, "")
    .replace(/\n?ESCALATE_GEMINI:\s*.+/i, "")
    .trim();
  return { clean, target, escalateReason: pick[1].trim() };
}
```

Update all call sites of `stripEscalateMarker` (orchestrator, tests if any).

### 1.5 `src/cursor/client.ts` — suggested shape

Mirror `src/gemini/client.ts`:

```typescript
const SECRET_KEY = "blossom.cursor.apiKey";

export async function getCursorApiKey(context: vscode.ExtensionContext): Promise<string | undefined> {
  return context.secrets.get(SECRET_KEY);
}

export async function callCursorAgent(opts: {
  apiKey: string;
  prompt: string;
  cwd: string;
  model?: string;
  signal?: AbortSignal;
}): Promise<{ text: string; status?: string }> {
  const { Agent } = await import("@cursor/sdk");
  const result = await Agent.prompt(opts.prompt, {
    apiKey: opts.apiKey,
    model: { id: opts.model ?? "composer-2.5" },
    local: { cwd: opts.cwd },
  });
  const text = typeof result.result === "string" ? result.result : JSON.stringify(result.result ?? "");
  return { text, status: String(result.status ?? "") };
}
```

**Verify against current SDK docs** before shipping — API is beta:
- https://cursor.com/docs/sdk/typescript
- Handle `CursorAgentError`, cancellation, timeout

**MCP / Ghidra (not automatic):** SDK defaults to `local.settingSources: []` (inline config only). IDE MCP servers (e.g. `user-ghidra`) are **not** inherited unless you:
1. Pass `local: { settingSources: ["all"] }` and verify from VS Code extension context, **or**
2. Pass **inline MCP** config mirroring Cursor’s Ghidra server (stdio command/args/env).

See [Testing checklist — MCP & vision parity](#mcp--vision-parity-p1--image-routing-p1b).

**Workspace root:** Use `vscode.workspace.workspaceFolders?.[0]?.uri.fsPath`. For multi-root, prefer folder containing active editor file, else first folder.

### 1.6 `src/cursor/escalate.ts` — confirm dialog

Mirror `escalateToGemini.ts` but:

- Title: `Blossom wants to call Cursor Agent (composer-2.5).`
- Warn: **Uses Cursor subscription tokens** (no exact $ estimate unless SDK returns usage)
- Buttons: `Allow Cursor` / `Cancel`
- On missing API key → `Set API Key` flow like Gemini

### 1.7 Conversation compression (required before **every** cloud escalate)

**Requirement:** Before **any** paid/cloud escalation — **Cursor, Gemini, Claude**, vision upload handoff, manual copy, or ChatRouter cloud fallback — compress and summarize the **full Blossom session** into one compact handoff block. **Reuse the same summary** when falling back between providers to avoid re-sending raw history and wasting tokens.

**Applies to:**

| Trigger | Compress? | Reuse summary on fallback? |
|---------|-----------|----------------------------|
| `ESCALATE_CURSOR` | **Yes** | → Gemini → Claude if Cursor declined/failed |
| `ESCALATE_GEMINI` | **Yes** (replace last-6-turns) | → Claude if Gemini failed (optional P1c) |
| `ESCALATE_CLAUDE` / extension Claude (P1c) | **Yes** | N/A (last resort) |
| Vision upload → Cursor | **Yes** + prior text context | → Gemini if Cursor declined (text-only; no vision) |
| `blossom.copyCursorHandoff` (P0) | **Yes** | User picks provider in Cursor IDE manually |
| ChatRouter `_cloud_facts()` (backend) | **Yes** (P2) | Gemini → Claude per `CLOUD_FALLBACK_ORDER` |

**Do not** dump raw `this.history` into any cloud prompt — editor dumps, fences, and tool rounds explode token cost across Cursor, Gemini, and Claude.

#### 1.7.1 Shared module: `src/escalate/compressHandoff.ts`

```typescript
export interface HandoffCompression {
  summaryMarkdown: string;
  rawChars: number;
  compressedChars: number;
  currentUserAsk: string;
  localAttempt?: string;
  /** Cache key — reuse across fallback chain within same turn */
  cacheId: string;
}

export async function compressConversationForHandoff(opts: {
  history: Array<{ role: string; content: string }>;
  escalateReason?: string;
  imageAttachments?: Array<{ path: string; metadata?: string }>;
  repoMapSnippet?: string;
  maxSummaryChars?: number;
  priorCursorAttempt?: string;  // if falling back from Cursor, include truncated Cursor reply
}): Promise<HandoffCompression>;
```

**Compression pipeline (run once per user turn, then reuse):**

1. **Collect** full session history from orchestrator.
2. **Strip noise** — collapse fences/tool_call blocks, strip `### Summary`, dedupe repo map.
3. **Summarize** to fixed schema:

```text
[BLOSSOM SESSION SUMMARY — compressed for handoff]
Goal: …
Prior decisions: …
Files mentioned / edited: …
Local attempts & failures: …
Open questions: …
Escalation reason: …
Prior turns (count): N
```

4. **LLM summarize** when raw history > threshold — use **local ChatRouter persona** or **Gemini Flash** (cheap); **never Cursor tokens** for summarization.
5. **Cap** at `blossom.handoff.maxSummaryChars` (default **6000**).
6. **Preserve verbatim** outside summary: current user ask (2000 cap) + local attempt (4000 cap).
7. **Cache** result on orchestrator for this turn (`handoffCache`) so Cursor → Gemini → Claude reuse identical summary without re-compressing.

**Status UI:** `Compressing conversation for cloud handoff…` (provider-agnostic message).

#### 1.7.2 Shared builder: `src/escalate/buildCloudHandoff.ts`

Single function; only the preamble and provider instructions differ:

```typescript
export type CloudHandoffProvider = "cursor" | "gemini" | "claude";

export function buildCloudHandoffPrompt(opts: {
  provider: CloudHandoffProvider;
  compressed: HandoffCompression;
  userText: string;
  localAttempt: string;
  workspace: string;
  repoMap?: string;
  activeFile?: string;
  toolErrors?: string;
  imageAttachments?: Array<{ path: string; metadata?: string }>;
  priorProviderAttempt?: { provider: string; text: string }; // fallback context
}): string;
```

**Provider preambles (same compressed body, different tail):**

| Provider | Preamble emphasis |
|----------|-------------------|
| **cursor** | Full agent tools, MCP, read images from disk paths |
| **gemini** | Text completion; actionable answer; fences if code |
| **claude** | Same as Gemini; Anthropic API via extension |

**Fallback appendix** (when Gemini/Claude follows Cursor):

```text
[PRIOR ESCALATION ATTEMPT — cursor]
The user already tried Cursor Agent. Below is a truncated result (may be incomplete):
…
Continue from the session summary above; do not restart from scratch.
```

#### 1.7.3 Fallback chain: Cursor → Gemini → Claude

**Setting:** `blossom.escalate.fallbackOrder` default `cursor,gemini,claude` (extension-side; respects enabled providers + API keys).

**Flow:**

```
1. compressConversationForHandoff()  — once
2. Try Cursor (if ESCALATE_CURSOR or vision.onAttach=escalate)
   → user confirms → SDK call
3. If declined / failed / disabled:
   → offer Gemini with SAME compressed handoff (+ optional truncated Cursor output)
4. If Gemini declined / failed:
   → offer Claude with SAME compressed handoff (+ prior attempts summary)
5. learnCodingLesson with source matching winning provider
```

**Token savings:** Summarize once (~1500 tokens max). Each cloud provider gets summary + verbatim current ask — **not** 45k chars raw history × 3 providers.

**Vision note:** If Cursor declined and user falls back to Gemini/Claude, include **image metadata + paths** in summary but warn user: “Gemini/Claude path is text-only unless multimodal wired — prefer Cursor for pixel work.”

#### 1.7.4 Refactor existing Gemini escalate (required P1)

**Replace** `orchestrator.ts` `buildEscalatePrompt` (last ~6 turns):

```typescript
// BEFORE (remove):
const recent = this.history.slice(-6)...

// AFTER:
const compressed = await compressConversationForHandoff({ history: this.history, ... });
const contextPrompt = buildCloudHandoffPrompt({
  provider: "gemini",
  compressed,
  userText,
  localAttempt,
  ...
});
await escalateToGemini(this.context, { reason, contextPrompt, systemPrompt: system });
```

Same pattern for new `escalateToClaude()`.

#### 1.7.5 Settings (shared handoff — not Cursor-only)

| Setting | Default | Purpose |
|---------|---------|---------|
| `blossom.handoff.maxSummaryChars` | `6000` | Cap compressed summary for **all** providers |
| `blossom.handoff.summarizeThresholdChars` | `12000` | Raw history above → LLM summarize step |
| `blossom.handoff.summarizeProvider` | `local` | `local` \| `gemini` \| `rules-only` — **pre-cloud** summarizer only |
| `blossom.escalate.fallbackOrder` | `cursor,gemini,claude` | Extension fallback chain |
| `blossom.escalate.reuseCompressionCache` | `true` | Same summary across fallback within one turn |
| `blossom.vision.onAttach` | `escalate` | Image → Cursor first in chain |

Keep provider-specific: `blossom.cursor.*`, `blossom.gemini.*`, `blossom.claude.*` (model ids, enabled flags).

**Deprecate:** `blossom.cursor.handoffMaxSummaryChars` — migrate to `blossom.handoff.*` (single namespace).

#### 1.7.6 `buildCursorHandoffPrompt` — thin wrapper

```typescript
// orchestrator.ts — delegate to shared builder
private async buildCursorHandoffPrompt(...): Promise<string> {
  const compressed = await compressConversationForHandoff({ ... });
  return buildCloudHandoffPrompt({ provider: "cursor", compressed, ... });
}
```

Pull `repoMap` from `repoKnowledge.ts`. Orchestrator awaits compression once, passes cached `compressed` to fallback chain.

#### 1.7.7 ChatRouter backend cloud (P2 — **shipped**)

When coding requests hit ChatRouter directly (not extension Gemini bypass), `_get_coding_intel()` → `_cloud_facts()` compresses via `CloudHandoffCompressor.py` before Gemini/Claude:

- **Option A:** Extension pre-compresses and sends `[BLOSSOM SESSION SUMMARY]` — detected and reused.
- **Option B (shipped):** `prepare_cloud_coding_prompt()` in `CloudHandoffCompressor.py` called inside `_get_coding_intel()` before `_cloud_facts()`.

Backend ladder **already** tries Gemini then Claude per `CLOUD_FALLBACK_ORDER` — **same compressed blob** to both; `append_prior_provider_block()` on provider failure.

### 1.8 Orchestrator integration (~orchestrator.ts after line 726)

```typescript
const { clean, target, escalateReason } = stripEscalateMarkers(assistantText);
let finalText = clean;

// Compress ONCE per turn — reuse for Cursor / Gemini / Claude fallback
const compressed = await compressConversationForHandoff({
  history: this.history,
  escalateReason,
  imageAttachments,
});
this.handoffCache = compressed;

if (escalateReason && target === "cursor" && getConfig().cursorEnabled) {
  const handoffPrompt = buildCloudHandoffPrompt({
    provider: "cursor", compressed, userText, localAttempt: clean, ...
  });
  const cursor = await escalateToCursor(this.context, { reason: escalateReason, contextPrompt: handoffPrompt });
  if (cursor.accepted && cursor.text) { /* learn source=blossom_assistant_cursor */ }
  else if (getConfig().escalateFallbackEnabled) {
    await runCloudFallbackChain({ compressed, afterCursor: cursor.text, ... }); // gemini → claude
  }
} else if (escalateReason && target === "gemini") {
  const handoffPrompt = buildCloudHandoffPrompt({ provider: "gemini", compressed, ... });
  await escalateToGemini(this.context, { reason: escalateReason, contextPrompt: handoffPrompt });
  // on fail → escalateToClaude with same compressed + priorProviderAttempt
}
```

**Optional (shipped P3):** Parse cloud escalation answers into Apply cards via `proposeCloudEdits.ts` — reuses `applyFromResponse.ts` after normalizing Cursor-style fences. Setting: `blossom.escalate.applyFromCloud` (default true). Prose-only cloud answers still require manual apply or P2 de-escalate retry.

### 1.9 Settings (`package.json` contributes.configuration)

```json
"blossom.cursor.enabled": {
  "type": "boolean",
  "default": true,
  "description": "Allow ESCALATE_CURSOR → Cursor SDK agent (uses Cursor subscription)."
},
"blossom.cursor.model": {
  "type": "string",
  "default": "composer-2.5",
  "description": "Cursor SDK model id for escalations."
},
"blossom.handoff.maxSummaryChars": {
  "type": "number",
  "default": 6000,
  "description": "Max chars for compressed session summary — Cursor, Gemini, Claude, manual handoff."
},
"blossom.handoff.summarizeThresholdChars": {
  "type": "number",
  "default": 12000,
  "description": "Raw history above this triggers LLM summarize before any cloud escalate."
},
"blossom.handoff.summarizeProvider": {
  "type": "string",
  "enum": ["local", "gemini", "rules-only"],
  "default": "local",
  "description": "Pre-cloud summarizer (never uses Cursor tokens)."
},
"blossom.escalate.fallbackOrder": {
  "type": "string",
  "default": "cursor,gemini,claude",
  "description": "When one provider fails/declined, offer next with same compressed handoff."
}
```

API key stays in **SecretStorage** only (`blossom.cursor.apiKey`), not in settings.json.

### 1.10 Dependencies

```bash
cd "C:\Users\Zepse\Documents\Blossom Assistant"
npm install @cursor/sdk
npm run compile
```

### 1.11 Acceptance criteria

- [ ] Model emits `ESCALATE_CURSOR: …` and orchestrator catches it
- [ ] User must confirm before Cursor SDK runs (modal, cancellable)
- [ ] **Conversation compressed once per turn** before Cursor, Gemini, and Claude
- [ ] **Same compressed summary reused** on Cursor → Gemini → Claude fallback (no triple raw history)
- [ ] **Gemini escalate refactored** — no more `buildEscalatePrompt` last-6-turns dump
- [ ] Fallback chain offers Gemini/Claude with prior provider attempt appendix when Cursor fails
- [ ] Confirm dialog shows approximate handoff size (chars or est. tokens) when compression completes
- [ ] Cursor answer labeled `*Cursor:*` in chat UI
- [ ] `POST /v1/memory/coding` with `source=blossom_assistant_cursor` on success
- [ ] `GET /v1/memory/coding?q=…` returns the new lesson
- [ ] Gemini path still works unchanged
- [ ] Missing API key / user decline / SDK error → soft-fail, local attempt remains visible
- [ ] `blossom.cursor.enabled=false` skips Cursor, optionally offers Gemini
- [ ] Compile clean; manual test on a real workspace folder
- [ ] **MCP parity test passes** (see [Testing checklist](#mcp--vision-parity-p1--image-routing-p1b))
- [ ] **Image path test passes** (SDK reads PNG from disk; see §1b)

---

## Must do #1b — Image upload & vision routing

**Context:** User may upload PNG/JPEG screenshots (Azahar texture dumps, UI chrome, BCLIM candidates) similar to Cursor chat attach. **Local Qwen3-Coder-30B cannot parse image pixels** — it is not a vision model in this deployment.

### Current state

| Layer | Image support |
|-------|----------------|
| Blossom Assistant UI | **Yes** — Attach image button; PNG/JPEG/WebP/GIF via file picker |
| ChatRouter | No `image_url` / multimodal message handling |
| llama-server GGUF | Text coder only (`Qwen3-Coder-30B-A3B`); `mtmd.dll` present in runtime but unused |
| Gemini escalate | Could add vision if `callGemini` sends image parts — not implemented |
| Cursor SDK escalate | Can read **file paths** from disk; chat-style attach TBD |

### Policy: do **not** send raw images to local Qwen

When image upload is implemented in Blossom Assistant:

| User action | Route | Rationale |
|-------------|-------|-----------|
| Attach PNG/JPEG/WebP/GIF | **Skip local coder** → offer Cursor escalate (or confirm-first auto-route) | Local GGUF has no vision encoder |
| Attach + “what is this texture / match BCLIM” | **Cursor escalate** (or Cursor IDE directly) | Needs vision and/or `image_map.py` + MAD tooling |
| Attach + optional text question | Prepend **image metadata** (see below) → still **escalate** for pixel work | Text summary helps handoff, not local inference |
| No attach — code/text only | Normal local ladder | Unchanged |

**Recommended default:** `blossom.vision.onAttach=escalate` — when any image is attached, **do not** call ChatRouter local coders; show:

> “Image attached — local Blossom coder is text-only. Escalate to Cursor Agent?”

User confirms → **compress full prior text conversation** (§1.7) → Cursor SDK with:
- compressed session summary (goals, prior turns, local attempts)
- current user message (verbatim)
- image path(s) + metadata

**Vision escalate must retain prior context:** Image upload is often turn 3+ in a thread (user discussed a bug, then attaches a dump). Never hand Cursor only the image line — always include compressed history from earlier text turns in the same Blossom chat session.

**Optional setting:** `blossom.vision.onAttach=metadata-only` — run lightweight preprocessor, send **text only** to local model (weak; may still emit `ESCALATE_CURSOR`).

### Image metadata preprocessor (optional P1b helper)

Before local or escalate path, extension can run a small Node/Python helper on attached files (no LLM vision required):

```text
[IMAGE METADATA]
path: C:\Users\...\tex1_16x16_ABC_mip0.png
size: 256×64
channels: RGBA
mean_rgb: 0.02, 0.01, 0.01  (alpha-only text chrome if ~0)
file_size_bytes: 12400
```

This matches NLPP workflow (note W×H, alpha vs opaque) from ui-localization rules — **local Qwen can use this text** to reason “likely A8 BCLIM chrome” vs “baked RGBA button,” but **cannot** pixel-match assets. Matching still escalates or runs `pack_images` / MAD scripts.

**Do not pretend** local Qwen “viewed” the image if only metadata was injected.

### Implementation sketch (Blossom Assistant)

**Files:**

- `src/chat/attachments.ts` — accept drag/drop + picker; store temp copies or workspace-relative paths
- `src/vision/metadata.ts` — PIL/sharp or call `python -c` for PNG stats
- `src/agent/orchestrator.ts` — before ChatRouter call:

```typescript
if (hasImageAttachments(turn)) {
  if (cfg.visionOnAttach === "escalate") {
    events.onStatus("Image attached — preparing Cursor handoff with session context…");
    const handoffPrompt = await buildCursorHandoffPrompt({
      history: this.history,           // full session — compress via §1.7
      userText,
      localAttempt: "",                // skipped local this turn
      imageAttachments,
      escalateReason: "Vision upload — local coder is text-only",
    });
    return offerCursorEscalateForImages({ contextPrompt: handoffPrompt });
  }
  // metadata-only: append metadata block to user prompt, then local (expect ESCALATE_CURSOR often)
}
```

**Handoff prompt addition for Cursor SDK:**

```text
Attached images (read these files from disk):
- C:\...\dump.png — 256×64 RGBA, mean RGB near 0 (alpha text chrome suspected)

Use Read/analyze tools on these paths. For romhack texture ID, prefer script evidence (MAD≈0) over guessing from filename.
```

### NLPP-specific note

Even **vision-capable** models are unreliable at exact BCLIM identity vs GPU dumps. Preferred pipeline:

1. Image attach → **escalate to Cursor** (or stay in Cursor IDE)
2. Cursor runs **Python MAD / `bclimutil` / `image_map.py`** — not raw “looks like X”
3. Store **text lesson** in Chroma: package id, filename, MAD score — not the PNG bytes

### Acceptance criteria (P1b — image routing)

- [x] Image attach in Blossom UI does **not** silently send pixels to local Qwen
- [x] Default behavior offers Cursor escalate with file paths + metadata
- [x] **Compressed prior conversation included** in vision escalate handoff (multi-turn context preserved)
- [x] User can cancel and stay local (gets metadata text only + explicit “no vision” warning)
- [x] Cursor SDK handoff includes absolute paths to attached files
- [x] After Cursor answers, 👍/👎 registers feedback (no binary in Chroma)
- [ ] Document in README: “images → escalate with session summary; text → local”

### What 70B upgrade changes (and doesn’t)

| After 70B text coder | Vision uploads |
|----------------------|----------------|
| Better code / reasoning on **text** | **Still no vision** unless you add a separate VLM GGUF + mmproj |
| Fewer escalations for hard **code** | Image attach policy **unchanged** — still escalate or add vision model |

Optional future: second local slot — small VLM (e.g. Qwen2-VL) for “describe this screenshot” only; keep coder separate. Large scope — defer.

---

## Must do #1c — Context interrupt & continue (Blossom Assistant)

**Owner repo:** `Blossom Assistant` only.

**Problem:** The agent tool loop can run for many rounds (read files, run commands, propose edits). The user often remembers missing context *while Blossom is still working*. Today the choices are bad:

| Option today | Pain |
|--------------|------|
| **Stop** then re-ask with more context | Loses in-flight work; must repeat the whole turn |
| **Wait** until the turn finishes | Wastes time; model may proceed down the wrong path |
| **Send another message** while busy | Input is blocked (`busy` disables Send) |

**Goal:** Allow **interrupting the in-progress turn with additional user context** and have the agent **continue thinking** with that new information — same chat tab, same turn, no full restart.

### UX spec

**While `busy` (agent running):**

| Control | Behavior |
|---------|----------|
| **Stop** | Unchanged — abort in-flight fetch / tool loop (`orchestrator.cancel()`) |
| **Add context** (new) | Enabled while busy; opens/focuses composer with placeholder “Add context for the current task…” |
| **Send** (when busy) | Becomes **“Add context”** — same as Add context button |

**After user submits mid-turn context:**

1. Show a compact **user inject bubble** in the trail: `Context added: …` (truncated).
2. Spinner continues — turn is **not** cancelled.
3. Status: `Incorporating your update…`

**When the agent incorporates it:**

- Inject appears in the **next tool-loop iteration** as a synthetic user message (see protocol below).
- If the model was waiting on `run_command` approval, inject is queued until after the command resolves (do not steal focus from Run/Deny).

**When the turn completes:** Final history includes the inject(s) so the next user message and any cloud escalate handoff see them.

### Orchestrator protocol

**New queue on `AgentOrchestrator`:**

```typescript
private pendingContextInjects: string[] = [];

/** Called from ChatPanel while busy — does NOT abort. */
addContextInject(text: string): void {
  const t = text.trim();
  if (!t) return;
  this.pendingContextInjects.push(t.slice(0, 4000));
}

/** Consumed at start of each tool-loop round in runToolLoop. */
private drainContextInjects(): string | undefined { ... }
```

**Inject format** (prepend to messages before the next model call):

```text
[USER CONTEXT UPDATE — mid-turn; prioritize this over earlier assumptions]
<verbatim user inject>

Continue the current task with this new information. Do not restart from scratch unless the update invalidates prior work.
```

**Rules:**

- **Do not** abort `AbortController` on inject — only Stop aborts.
- **Do not** push inject into `this.history` until the turn completes (avoid duplicate user rows mid-stream); queue only for the active loop.
- **Do** include drained injects in `compressConversationForHandoff()` if the turn later escalates to Cursor/Gemini.
- **Cap:** max **3 injects per turn**; further injects show “Queue full — Stop or wait for this turn to finish.”
- **Cap:** max **4000 chars** per inject.

### ChatPanel / webview changes

| File | Changes |
|------|---------|
| `src/chat/ChatPanel.ts` | While `busy`, enable composer + relabel Send → “Add context”; post `{ type: 'addContext', text }` |
| `src/agent/orchestrator.ts` | `addContextInject()`; drain in `runToolLoop`; merge into completed turn history on `onDone` |

**Webview behavior:**

```javascript
function sendText(text, opts) {
  const ask = (text || '').trim();
  if (!ask) return;
  if (busy && !(opts && opts.retry)) {
    append('user', ask, { inject: true }); // styled as mid-turn inject
    input.value = '';
    vscode.postMessage({ type: 'addContext', text: ask });
    return;
  }
  // ... existing send
}
```

### Acceptance criteria (P1c-interrupt)

- [x] User can submit text while agent is busy without hitting Stop
- [x] In-flight ChatRouter stream is **not** aborted by inject (unless user hits Stop)
- [x] Next tool-loop round’s model call includes `[USER CONTEXT UPDATE]` block
- [x] Inject visible in UI trail as “Context added”
- [x] Multiple injects queue in order (max 3 per turn)
- [x] Completed turn history + escalate handoff include injects
- [x] `run_command` pending card still blocks until Run/Deny; inject queues behind it
- [x] Stop still cancels everything including queued injects

### Anti-patterns

- Aborting the current fetch on every inject (too disruptive)
- Starting a **new** parallel orchestrator turn while one is busy
- Silently dropping injects with no UI acknowledgement

### Priority

| Priority | Task | Repo | Effort |
|----------|------|------|--------|
| **P1c-interrupt** | Context inject while busy + continue tool loop | Blossom Assistant | Medium |

Place after **P1b** (vision) and before Claude extension escalate (**P1c-cloud** rename if needed).

### De-escalate (cloud → local Blossom) — **shipped P2-deescalate (v0.1.50)**

Escalation is **up** (local → cloud) and **down** (cloud → local retry):

| Scenario | Fall back to local Blossom? |
|----------|----------------------------|
| User declines Cursor/Gemini/Claude confirm modal | **Yes** — local attempt stays visible; no cloud appendix |
| Vision attach → “Stay local (metadata only)” | **Yes** — metadata text injected; local coder runs |
| Vision/Cursor escalate declined → metadata fallback | **Yes** |
| Cursor/Gemini/Claude **answered** this turn | **Retry offered** — chat button **Retry with local Blossom**; 👎 also prompts retry |
| Local retry after cloud | **Yes** — cloud answer prepended as read-only reference; local tool loop runs; result merges local + cloud + local retry sections |
| ChatRouter ladder after cloud exhaust | **N/A in extension** — extension bypasses ladder for confirm-gated escalate |

**Implementation (v0.1.50):**

| Piece | Location |
|-------|----------|
| Snapshot after cloud success | `orchestrator.ts` — `lastCloudEscalation` |
| `retryWithLocalBlossom()` | `orchestrator.ts` — pops cloud assistant from history, runs local tool loop |
| De-escalate prompt | `src/escalate/deescalate.ts` — `buildDeescalateRetryPrompt()` |
| Chat UI button | `ChatPanel.ts` — after cloud reply when `deescalateAvailable` |
| 👎 path | `ChatPanel.ts` — info message “Retry locally?” |
| Command | `blossom.retryWithLocal` |
| Setting | `blossom.deescalate.enabled` (default `true`) |
| Feedback source | `blossom_assistant_deescalate` via `/v1/feedback/register` |

**Policy:** One retry per cloud answer (snapshot cleared on retry start). Further cloud escalation markers during de-escalate retry are stripped — no auto re-escalate.

---

## Must do #2 — Manual handoff (P0)

Ship **before** or **in parallel with** SDK work so user gets value immediately.

### 2.1 Command: `blossom.copyCursorHandoff`

**File:** new `src/cursor/handoff.ts`

1. Gather: user request, local attempt (if any), **`compressConversationForHandoff()` output**, image paths
2. Write JSON to `.blossom/handoff.json` in workspace (create dir if needed, add to `.gitignore` recommendation)
3. Copy markdown handoff to clipboard
4. Show info: `Handoff copied (session summarized). Open Cursor in this workspace → paste into Agent chat.`

**`.blossom/handoff.json` schema:**

```json
{
  "version": 2,
  "created_at": "2026-08-02T20:00:00Z",
  "user_prompt": "...",
  "local_attempt": "...",
  "conversation_summary": "...",
  "compression": { "raw_chars": 45000, "compressed_chars": 5800 },
  "image_attachments": [{ "path": "...", "metadata": "256x64 RGBA" }],
  "reason": "optional ESCALATE_CURSOR or vision upload",
  "workspace": "C:\\Users\\...",
  "source": "blossom_assistant_manual"
}
```

### 2.2 Command: `blossom.learnFromClipboard`

1. Read clipboard text as `answer`
2. Prompt user for one-line `user_prompt` (prefill from last user message if available)
3. `learnCodingLesson({ userPrompt, answer, source: "cursor_manual" })`
4. Show stored lesson id or error

### 2.3 PowerShell fallback (no extension build)

```powershell
curl -X POST http://127.0.0.1:8081/v1/memory/coding `
  -H "Content-Type: application/json" `
  -d '{"user_prompt":"How do I fix X","answer":"Cursor solution text here","source":"cursor_manual"}'
```

Verify:

```powershell
curl "http://127.0.0.1:8081/v1/memory/coding?q=fix+X&n=3"
```

---

## Must do #3 — Cost / routing playbook

### Recommended workflow (user)

| Task type | Tool |
|-----------|------|
| Routine edits, Apply, refactors, small bugs | Blossom Assistant + ChatRouter |
| **Image / screenshot / texture dump attached** | **Cursor escalate or Cursor IDE** — not local Qwen |
| Uncertain, multi-file, needs shell/MCP | `ESCALATE_CURSOR` (confirm) |
| NLPP / Ghidra / long RE sessions | **Cursor directly** — don’t round-trip through Blossom |
| Text-only stuck (no tools needed) | `ESCALATE_GEMINI` or ChatRouter cloud |

### Cost mechanics

| Layer | Paid how |
|-------|----------|
| Local Qwen + DeepSeek | GPU electricity |
| ChatRouter Gemini/Claude | User’s Google/Anthropic API keys |
| Extension Gemini escalate | User’s Gemini API key + local spend tracker |
| Extension Cursor escalate | **Cursor subscription tokens** |
| Cursor Tab / Composer (direct use) | Cursor subscription |

**Savings come from:** local handling ~70%+ of tasks; Gemini before Claude; `CLOUD_ESCALATE_ON_INCOMPLETE=false`; Cursor only on confirmed hard escalations.

**Double-spend trap:** weak local answer → Cursor fixes → local retries same task badly → Cursor again. Mitigate with RAG (lesson should surface on retry) and Correct/Incorrect curation.

---

## Must do #4 — Improve coding over time

### Phase A — RAG (now, no GPU training)

1. **Auto-learn** on every successful coding path (already on)
2. **Correct/Incorrect** in Companion UI — curate noise
3. **Manual domain lessons** for repeat patterns (NLPP example topics) — **one-time seeded** (2026-08-02); lessons remain in Chroma. Re-run only if needed: `python tools/seed/seed_nlpp_lessons.py`
   - exact-zlib img.bin splice (`cmp_len` fixed, no NUL-pad)
   - BCLIM same-size replace vs Title.arc abs-align grow (pkg 5261)
   - TextResource hierarchy `FUN_005c0e7c` pack+slot vs flat STRI
   - UI chrome = texture not TRB when TRB already EN
4. **Compress `coding_rules.txt`** — split into intent-specific injects; keep always-on core under ~800 tokens

### Phase B — Eval harness (**P4 shipped** — `tools/eval/`)

**Corpus-agnostic** runner (PHP, C#, RE/assembly, any domain). First bundled corpus: `php-modernization`; templates for C# and reverse-engineering.

1. `python tools/eval/run_eval.py run --corpus php-modernization` — copy fixtures, prompt ChatRouter, apply `path=` fences, score checks
2. Checks: file contains/not_contains, regex, shell command (`php -l`, `dotnet build`), **response-only** for Ghidra/assembly prose
3. Failures → feed `coding_lessons` / rule updates manually (Phase A)
4. Pass rate tracked in `Mind/eval_results.db` via `run_eval.py report`
5. Plug in external `blossom-php-modernization-training-set` by matching the `corpora/*/corpus.json` layout

### Phase C — LoRA (**P6 shipped** — `tools/lora/`)

**Only for frozen habits:** PLAN → fences with `path=` → CREATE vs EDIT → Summary card.

**Not for:** project facts, one-off lessons, Chroma memories.

**Pipeline:**

1. `python tools/lora/export_dataset.py` — 👍 `feedback_turns` + optional `coding_rules.txt` → ShareGPT/Alpaca JSONL in `Mind/lora_exports/`
2. `python tools/lora/train_qlora.py` — QLoRA via Unsloth (optional GPU venv; see `requirements-train.txt`)
3. Merge adapter → GGUF manually (Unsloth / llama.cpp docs) → `Brains/models/coding/`
4. A/B via `CODER_MODELS` + `python tools/eval/run_eval.py report`

See **[tools/lora/README.md](./tools/lora/README.md)**.

---

## Must do #5 — ChatRouter alignment (optional P2)

**Recommendation:** Keep Cursor/Gemini/Claude **extension escalate** as primary for Assistant users. ChatRouter lacks VS Code workspace and MCP.

**Cloud compression (P2 — shipped):** When `_get_coding_intel()` falls through to `_cloud_facts()`:

1. `CloudHandoffCompressor.prepare_cloud_coding_prompt()` compresses session/editor context **once** before the first cloud call
2. **Same compressed blob** goes to Claude if Gemini fails — `append_prior_provider_block()` adds `[PRIOR ESCALATION ATTEMPT — gemini]`
3. Schema mirrors `src/escalate/compressHandoff.ts` / `buildCloudHandoff.ts`
4. Env: `HANDOFF_MAX_SUMMARY_CHARS`, `HANDOFF_SUMMARIZE_THRESHOLD_CHARS`, `HANDOFF_SUMMARIZE_PROVIDER`
5. Skips re-compression when caller already sent `[BLOSSOM SESSION SUMMARY]` (extension Option A)

Optional minor updates:

- `GET /health` → add `"supports_cursor_escalate": false` until/unless backend ever proxies
- Do **not** add `ESCALATE_CURSOR` handling in `_local_answer_requests_escalate()` unless ChatRouter gains a Cursor SDK client (unlikely)

**Do not** implement Cursor Override URL → ChatRouter tunnel as primary architecture.

---

## Must do #6 — Docs & README migration (required)

**Gate:** Do not mark P0/P1 “done” until this section is complete. `MustDo.md` is the implementation spec; **`README.md` is the user-facing home** after shipping.

### 6.1 Migrate to `Blossom/README.md` (required on P0+P1 complete)

Add or expand these sections in **`README.md`**. Copy/adapt from this file — do not leave vision only in `MustDo.md`.

| README section | Source in MustDo.md | Content to include |
|----------------|---------------------|-------------------|
| **Vision** (new) | [Vision & viability assessment](#vision--viability-assessment) | North star diagram, verdict table (merit vs pipe dream), anti-goals |
| **Hybrid workflow** (new) | [Must do #3](#must-do-3--cost--routing-playbook) | Which tool for which task; Blossom vs Cursor lanes |
| **Escalation** (new) | [Must do #1](#must-do-1--cursor-escalate-full-spec), [#2](#must-do-2--manual-handoff-p0) | `ESCALATE_CURSOR` / `ESCALATE_GEMINI`, manual handoff commands, confirm-before-call |
| **Images & vision** (new) | [Must do #1b](#must-do-1b--image-upload--vision-routing) | Text-only local coder; image attach → escalate **with compressed prior context** |
| **Handoff compression** (new) | [Must do §1.7](#17-conversation-compression-required-before-every-cloud-escalate) | Summarize once; reuse for Cursor → Gemini → Claude; reduce tokens |
| **Learning** (new) | [Must do #4 Phase A](#phase-a--rag-now-no-gpu-training) | RAG ≠ weight training; Correct/Incorrect; `/v1/memory/coding` |
| **Hardware & models** (expand) | [70B upgrade plan](#70b-upgrade-plan-future--when-funded) | Current 4090 + 30B MoE; future 70B requirements; **do not** repeat 72B spill on 24 GB |
| **Quick start** (keep) | existing | Point to Brains, `.env`, `start-server.ps1` |
| **Where we're at** (keep) | existing | Link `PROGRESS.md`; add link to `MustDo.md` for active work only |

**README tone:** User-facing, concise — 1–2 screens per section. Move implementation checklists and code sketches to `MustDo.md` or `PROGRESS.md`.

**Acceptance criteria:**

- [x] New clone/read of `README.md` explains *why* Blossom exists and *when* to use Cursor without opening `MustDo.md`
- [x] 70B plan documented as future hardware milestone (not current 4090 path)
- [x] Escalation setup (API keys, commands) documented for Blossom Assistant
- [x] `MustDo.md` retains full spec; README links to it as “Active implementation spec”

### 6.2 Other doc updates (required on P1 complete)

- [ ] `Blossom/PROGRESS.md` — session log: Cursor escalate + learn path shipped
- [ ] `Blossom Assistant/README.md` — Cursor API key, `ESCALATE_CURSOR`, manual handoff commands, cost note
- [ ] `Blossom Assistant/progress.md` — session log entry
- [ ] `PythonScripts/.env.example` — comment: Cursor escalate is extension-side

### 6.3 Optional cross-links

- [ ] `Blossom Companion/README.md` — Correct/Incorrect affects `coding_lessons`
- [ ] `Brains/README.md` — 70B preset notes when hardware upgrade happens

### 6.4 README migration checklist (copy for PR)

```markdown
## README migration (P0/P1 gate)

- [x] Vision & north star in README.md
- [x] Merit vs pipe dream summary in README.md
- [x] Hybrid workflow (Blossom / Cursor / cloud) in README.md
- [x] Escalation types + setup in README.md
- [x] Learning (RAG vs LoRA) in README.md
- [x] Current hardware (4090/30B) + future 70B plan in README.md
- [x] Link to MustDo.md as active spec
- [x] PROGRESS.md updated
- [ ] Blossom Assistant/README.md updated
```

---

## API reference

### `POST /v1/memory/coding`

**Body:**

```json
{
  "user_prompt": "string (required, max ~2000 in extension client)",
  "answer": "string (required, max ~8000 in extension client)",
  "source": "blossom_assistant_cursor"
}
```

**Success:**

```json
{ "ok": true, "stored": true, "id": "<uuid>", "source": "blossom_assistant_cursor" }
```

**Skipped (answer not useful):**

```json
{ "ok": false, "stored": false, "reason": "answer not useful enough to store" }
```

### `GET /v1/memory/coding?q=<query>&n=5`

Returns `{ ok, count, memories: [{ id, text, metadata }] }`.

### `POST /v1/feedback`

```json
{ "feedback_id": "<from chat response>", "verdict": "correct" | "incorrect", "note": "optional" }
```

### `GET /health`

Check `coder_ladder_available`, `cloud_providers.order`, `supports_memory_write`.

---

## Testing checklist

### Manual handoff (P0)

- [ ] `copyCursorHandoff` writes `.blossom/handoff.json` and clipboard
- [ ] Paste in Cursor Agent → sensible takeover context
- [ ] `learnFromClipboard` stores retrievable lesson

### Cursor SDK escalate (P1)

- [ ] Local model emits `ESCALATE_CURSOR: need Ghidra xref`
- [ ] Confirm dialog appears; Cancel leaves local attempt only
- [ ] Allow runs SDK; answer appears with `*Cursor:*` prefix
- [ ] Chroma contains new lesson with correct source
- [ ] Second similar ask retrieves lesson in ChatRouter logs (watch `[Blossom]:` RAG inject)

### MCP & vision parity (P1 + P1b)

**Ghidra MCP test** (requires Ghidra running + MCP configured):

1. Trigger `ESCALATE_CURSOR` with prompt: `Find xrefs to string OptionMenu_BindBtnTextures in code.bin`
2. Pass: SDK agent invokes Ghidra MCP tools (check thought log / tool trace)
3. Fail: agent guesses without tools → document fallback: use **manual handoff → Cursor IDE**

**Image path test** (no chat attach required):

1. Attach or reference Azahar dump PNG path, e.g. `%AppData%\Azahar\dump\textures\00040000000F4E00\tex1_*.png`
2. Prompt: `Describe this texture and whether it looks like alpha-only UI chrome`
3. Pass: SDK agent reads file from disk and answers with plausible W×H / alpha assessment
4. Fail: agent hallucinates without reading → fix handoff paths or MCP/file tools

**Image upload routing test (P1b):**

1. User attaches PNG in Blossom Assistant chat
2. Pass: local Qwen **not** invoked; user offered Cursor escalate with paths + metadata
3. **Multi-turn test:** user sends 2–3 text messages, then attaches image → handoff includes compressed summary of earlier text turns (not image-only)
4. Cancel escalate: user sees warning that local model cannot see images

**Conversation compression test (P1 + P1b + P1c):**

1. Long session (10+ turns with fences/tool output) → trigger `ESCALATE_CURSOR`
2. Pass: handoff uses `[BLOSSOM SESSION SUMMARY]` block; raw history not pasted wholesale
3. Pass: `compressed_chars` < `raw_chars` and under `handoff.maxSummaryChars`
4. Pass: Cursor answer demonstrates awareness of earlier-turn goal (e.g. file path from turn 1)
5. **Fallback test:** Decline Cursor → offer Gemini → same `compressed_chars` in dialog (cache reused, not re-summarized)
6. **Fallback test:** Gemini fails → offer Claude with `[PRIOR ESCALATION ATTEMPT — gemini]` appendix
7. **Gemini direct test:** `ESCALATE_GEMINI` uses compressed handoff (not last-6-turns)
8. Confirm dialog shows handoff size estimate before Allow

### Regression

- [ ] `ESCALATE_GEMINI` still works
- [ ] ChatRouter coding route unchanged when extension not escalating
- [ ] Apply/auto-apply still works for local fences
- [ ] No secrets in settings.json or git

---

## Try later (manual verification)

Ship first, validate when convenient. Do not block the next implementation item on these unless regressions show up in daily use.

### P2-deescalate (v0.1.50)

- [ ] After cloud answer (`*Cursor:*` / `*Gemini:*` / `*Claude:*` appendix), **Retry with local Blossom** button appears
- [ ] Click retry → new **Local retry** segment streams; local tool loop runs (Apply cards if proposed)
- [ ] 👎 on cloud answer → “Retry locally?” prompt → same retry flow
- [ ] Command palette: `Blossom: Retry with Local Blossom` works on active chat tab
- [ ] `blossom.deescalate.enabled=false` hides button / blocks retry
- [ ] Second retry on same turn not offered (snapshot cleared after first retry)
- [ ] 👍/👎 on merged answer registers `blossom_assistant_deescalate` feedback turn

### Escalation / handoff / vision (from checklist above)

- [ ] Full [Testing checklist](#testing-checklist) — MCP parity, compression, fallback chain, P1b image routing
- [ ] `learnFromClipboard` — **skipped by design** (use 👍/👎 instead)

### P2 ChatRouter cloud compression (backend)

- [ ] Trigger cloud fallback (weak local / `ESCALATE_CLOUD`) → thought trail shows `cloud_compress` step
- [ ] `compressed_chars` < `raw_chars` for large editor dumps
- [ ] Gemini fail → Claude receives same base summary + `[PRIOR ESCALATION ATTEMPT — gemini]`
- [ ] Pre-compressed `[BLOSSOM SESSION SUMMARY]` in user message → skip re-compression (`already_compressed`)

### P3 cloud → Apply cards (v0.1.51)

- [ ] Cloud answer with ` ```typescript path=foo.ts ` fence → Apply card appears after cloud appendix
- [ ] Click Apply writes file; auto-apply respects session toggle
- [ ] Cursor ` ```lang:path/to/file ` style normalized and parsed
- [ ] Prose-only cloud answer → no Apply cards (expected)
- [ ] `blossom.escalate.applyFromCloud=false` disables parsing

### P4 eval harness (tools/eval)

- [ ] `python tools/eval/run_eval.py run --corpus php-modernization` with ChatRouter up
- [ ] `run_eval.py report` shows pass rate in `Mind/eval_results.db`
- [ ] Add external corpus path (e.g. `blossom-php-modernization-training-set`) using same layout
- [ ] RE/assembly task with `mode: analyze_only` scores response text

### P4 startup eval (start-server.ps1 + ChatRouter lifespan)

- [ ] `start-server.ps1` prints “Eval harness: installing tools/eval requirements…” and pip succeeds
- [ ] After ChatRouter listens, console shows `[Blossom Eval]` lines: `list` → `dry-run` → `run` → `report`
- [ ] `Mind/eval_results.db` gains a new row after boot (when live eval runs)
- [ ] `EVAL_ON_STARTUP=false` in `.env` skips pip install message + startup eval task
- [ ] `EVAL_ON_STARTUP_DRY_RUN_ONLY=true` runs list + dry-run + report only (no LLM call on boot)
- [ ] `EVAL_CORPUS=example-reverse-engineering` runs that corpus instead of PHP
### P5 NLPP domain seeds (one-time — done)

- [x] Four lessons inserted into Chroma (`seed_id` metadata)
- [ ] Optional: confirm RAG inject on img.bin / BCLIM / TRB chrome ask
- Re-seed only if Chroma wiped: `python tools/seed/seed_nlpp_lessons.py`

### P6 LoRA pipeline (tools/lora)

- [ ] `python tools/lora/export_dataset.py` writes `Mind/lora_exports/*.jsonl`
- [ ] Re-run after 👍 on coding turns increases `feedback_examples` count
- [ ] `train_qlora.py --dry-run` loads dataset without GPU deps
- [ ] Full train + merge → GGUF → ladder A/B (manual GPU step — try when ≥20 👍 examples)

---

## Anti-patterns (do not do)

1. **Tunnel ChatRouter to Cursor Override URL** — loses RAG/tools; still burns Cursor tokens
2. **Auto-run Cursor without user confirm** — expensive and surprising
3. **Fine-tune GGUF from every lesson** — use RAG first; LoRA only for stable format habits
4. **Store full repo dumps in Chroma** — lessons truncated by design; store patterns not files
5. **Enable `CLOUD_ESCALATE_ON_INCOMPLETE=true`** — burns Claude on heuristic false positives
6. **Run 72B hybrid coder on 24GB** — already rejected (~0.35 tok/s)
7. **Commit API keys, chromadb, or GGUFs**
8. **Send image attachments to local Qwen3-Coder** — text-only GGUF; use escalate or metadata preprocessor
9. **Expect local 30B/70B to pixel-match BCLIM dumps** — use MAD scripts + escalate
10. **Re-compress on Cursor → Gemini → Claude fallback** — reuse `handoffCache` from same turn
11. **Send raw last-6-turns to Gemini** — use shared `compressConversationForHandoff()` everywhere

---

## Implementation order

| Priority | Task | Repo | Effort |
|----------|------|------|--------|
| **P0** | `copyCursorHandoff` command | Blossom Assistant | Small — **done** |
| **P1** | `ESCALATE_CURSOR` + SDK + shared **compressHandoff** + 👍/👎 learn | Blossom Assistant | Medium — **done** |
| **P1b** | Image attach + `vision.onAttach=escalate` + compressed context | Blossom Assistant | Medium — **done** |
| **P1c-interrupt** | Mid-turn **context inject** while busy; continue tool loop | Blossom Assistant | Medium — **done** |
| **P1c-cloud** | Claude escalate + **ask-first** escalation picker | Blossom Assistant | Medium — **done** |
| **P2-deescalate** | Retry with local Blossom after cloud answer | Blossom Assistant | Small — **done** |
| **P2** | ChatRouter `_cloud_facts` compression (Gemini → Claude reuse) | Blossom | Small — **done** |
| **P3** | Parse Cursor/cloud output → Apply cards (if feasible) | Blossom Assistant | Medium — **done** |
| **P4** | Coding eval harness (`tools/eval`, multi-domain corpora) | Blossom/tools | Medium — **done** |
| **P5** | NLPP domain lesson seed pack | Blossom | Small — **done** (`tools/seed/`) |
| **P6** | LoRA pipeline | `tools/lora/` | Medium — **done** (export + train script; merge/GGUF manual) |
| **P7** | **README.md migration** | Blossom | Small — **done** |

---

## Open questions

1. **SDK vs IDE parity** — Does `@cursor/sdk` local agent expose same MCP servers (Ghidra) as Cursor IDE? Test early (see testing checklist).
2. **Image chat attach vs file path** — SDK may only read paths; confirm whether binary attach works like Cursor IDE chat.
3. **Model id** — `composer-2.5` vs Auto Cost — user-configurable default?
3. **Both markers in one reply** — Prefer Cursor over Gemini if both present (current spec)
4. **Multi-root workspace** — Which `cwd` for SDK when editor file is in folder B?
5. **Async/streaming** — SDK may support streaming; Blossom UI expects token events — follow Gemini pattern (wait for full text) first
6. **Apply from Cursor answer** — **P3 shipped:** fenced `path=` blocks in cloud text become Apply cards; prose-only answers still manual / de-escalate retry

---

## References

| Resource | Path / URL |
|----------|------------|
| Gemini escalate (clone this) | `Blossom Assistant/src/gemini/escalate.ts` |
| Orchestrator hook | `Blossom Assistant/src/agent/orchestrator.ts` ~726–755 |
| Escalate strip | `Blossom Assistant/src/agent/prompts.ts` `stripEscalateMarker` |
| Learn client | `Blossom Assistant/src/memory/client.ts` |
| ChatRouter learn | `Blossom/PythonScripts/SemanticMemory.py` `learn_coding_lesson` |
| Memory API | `Blossom/PythonScripts/ChatRouter.py` `@app.post("/v1/memory/coding")` |
| Coder ladder | `Blossom/PythonScripts/LocalModels.py` |
| Cloud policy | `Blossom/PythonScripts/.env.example` |
| Cursor SDK | https://cursor.com/docs/sdk/typescript |
| Eval corpus | `blossom-php-modernization-training-set/README.md` |
| Historical status | `Blossom/PROGRESS.md` |

---

## LLM agent onboarding prompt

Copy everything inside the block below and paste it as the **first message** to a new Cursor/Claude/GPT agent that will implement this work.

```markdown
# Agent briefing: Blossom → Cursor escalation

You are implementing **Cursor Agent escalation** for the Blossom local-first coding stack on Windows. Read `C:\Users\Zepse\Documents\Blossom\MustDo.md` in full before editing anything.

## Your mission

1. **P0 (ship first):** Add manual handoff commands to **Blossom Assistant** (VS Code extension):
   - `blossom.copyCursorHandoff` — build handoff packet (user request, local attempt, repo map, history), write `.blossom/handoff.json`, copy markdown to clipboard
   - `blossom.learnFromClipboard` — POST answer to ChatRouter `POST /v1/memory/coding` with `source=cursor_manual`

2. **P1 (main feature):** Clone the existing **Gemini escalate** pattern for **Cursor SDK**:
   - Add `ESCALATE_CURSOR: <reason>` to `src/agent/prompts.ts` (`CODING_AGENT_PROMPT`)
   - Replace/extend `stripEscalateMarker` to handle both `ESCALATE_CURSOR` and `ESCALATE_GEMINI` (prefer Cursor if both)
   - Create `src/escalate/compressHandoff.ts`, `buildCloudHandoff.ts`, `fallbackChain.ts`
   - Create `src/cursor/client.ts`, `src/cursor/escalate.ts` mirroring `src/gemini/*`
   - **Refactor `src/gemini/escalate.ts`** to use shared compression (remove last-6-turns)
   - Add `src/claude/escalate.ts` (P1c) — same compressed handoff as Gemini/Cursor
   - Fallback chain: Cursor declined/failed → Gemini → Claude with **reused** summary (§1.7.3)
   - Use `@cursor/sdk` `Agent.prompt()` with `local: { cwd: workspaceRoot }`
   - Hook in `src/agent/orchestrator.ts` after model reply — user confirm modal required
   - On success: `learnCodingLesson({ source: "blossom_assistant_cursor" })` via existing `src/memory/client.ts`
   - Register settings/commands in `package.json` + `src/extension.ts`

## Repos (do not confuse them)

| Path | What it is |
|------|------------|
| `C:\Users\Zepse\Documents\Blossom` | Python ChatRouter backend :8081, Chroma, llama-server — **do not add Cursor SDK here** |
| `C:\Users\Zepse\Documents\Blossom Assistant` | VS Code extension — **all P0/P1 work goes here** |
| `C:\Users\Zepse\Documents\Blossom Companion` | Nuxt chat UI — out of scope unless asked |

## Architecture you must preserve

- Blossom Assistant → `http://127.0.0.1:8081/v1/chat/completions` (ChatRouter)
- ChatRouter coding path: Qwen3-Coder-30B → DeepSeek-Coder-V2-Lite → Gemini → Claude
- Learning = **Chroma RAG** (`coding_lessons`), **NOT** GGUF weight updates
- Gemini escalate already works — **do not break it**
- API keys in VS Code **SecretStorage**, never in settings.json or git

## Reference implementation (clone this exactly)

Study these files before writing code:

1. `Blossom Assistant/src/gemini/escalate.ts` — confirm dialog, call external API, return `{ accepted, text, cancelledReason }`
2. `Blossom Assistant/src/gemini/client.ts` — SecretStorage key pattern
3. `Blossom Assistant/src/agent/orchestrator.ts` lines ~726–755 — escalate hook + learnCodingLesson
4. `Blossom Assistant/src/agent/prompts.ts` — `ESCALATE_GEMINI` contract + `stripEscalateMarker`
5. `Blossom Assistant/src/memory/client.ts` — `learnCodingLesson()`
6. `Blossom Assistant/src/config.ts` + `package.json` — how Gemini settings are wired

## Cursor SDK usage (verify docs — beta API)

```typescript
import { Agent } from "@cursor/sdk";

const result = await Agent.prompt(handoffPrompt, {
  apiKey: cursorApiKey,
  model: { id: "composer-2.5" },
  local: { cwd: vscode.workspace.workspaceFolders![0].uri.fsPath },
});
```

Docs: https://cursor.com/docs/sdk/typescript

Handoff prompt must include: workspace path, **compressed session summary** (full prior conversation, not raw dumps), current user ask (verbatim), local attempt, repo knowledge snippet, reason, image paths when applicable.

**Before every cloud call (Cursor, Gemini, Claude):** run `compressConversationForHandoff()` **once per turn**; reuse cached summary on fallback chain. Never re-send raw history to each provider.

Summarization uses **local persona or Gemini Flash** — not Cursor tokens.

## Memory API (after Cursor succeeds)

```http
POST http://127.0.0.1:8081/v1/memory/coding
Content-Type: application/json

{
  "user_prompt": "<original task>",
  "answer": "<cursor agent full reply>",
  "source": "blossom_assistant_cursor"
}
```

ChatRouter must be running (`Blossom/start-server.ps1`). Soft-fail if down — escalate should not crash the chat session.

## UX requirements

- **Always** show modal confirm before calling Cursor SDK (like Gemini)
- Label Cursor replies `*Cursor:*` in chat (match `*Gemini:*` pattern)
- User decline / missing API key / SDK error → keep local attempt visible, no throw
- Add `blossom.setCursorApiKey` command (mirror `blossom.setGeminiApiKey`)

## Do NOT

- Point Cursor IDE Override URL at ChatRouter as the “fix”
- Auto-run Cursor without user confirmation
- Add Cursor SDK to Python ChatRouter (extension-only)
- Break existing `ESCALATE_GEMINI` flow
- Commit secrets, API keys, or `.blossom/handoff.json` with sensitive content
- Enable `CLOUD_ESCALATE_ON_INCOMPLETE` in backend env (user keeps it false to save $)

## Build & test

```powershell
cd "C:\Users\Zepse\Documents\Blossom Assistant"
npm install @cursor/sdk
npm run compile
# F5 to launch Extension Development Host
# Ensure Blossom ChatRouter running: C:\Users\Zepse\Documents\Blossom\start-server.ps1
```

Test cases:
1. Model emits `ESCALATE_CURSOR: …` → confirm → Cursor answer → lesson in Chroma
2. Cancel confirm → local attempt remains
3. `ESCALATE_GEMINI` still works
4. `copyCursorHandoff` + paste in Cursor IDE → sensible context
5. `learnFromClipboard` → `GET /v1/memory/coding?q=…` finds lesson

## When done

1. Update `Blossom/MustDo.md` checkboxes (including README migration gate in MustDo #6).
2. **Required:** Migrate vision, hybrid workflow, escalation, **image routing policy**, learning, and 70B plan into **`Blossom/README.md`** per MustDo §6.1.
3. Update `Blossom/PROGRESS.md`, `Blossom Assistant/progress.md`, and `Blossom Assistant/README.md`.

Read MustDo § [Vision & viability assessment](#vision--viability-assessment) and § [1b Image upload](#must-do-1b--image-upload--vision-routing).

### Image routing rule (implement P1b)

Local Qwen3-Coder-30B is **text-only**. Image attach → **do not** call local coder; **compress session history** → offer Cursor escalate with file paths + metadata + prior context. 70B text upgrade does **not** change this unless a separate VLM is added.

### Compression rule (implement P1 + P1c)

Never send raw Blossom history to **any** cloud provider. Compress once per turn (§1.7). Reuse cache on **Cursor → Gemini → Claude** fallback. Refactor existing Gemini escalate off `buildEscalatePrompt` last-6-turns. Summarization uses local ChatRouter persona or Gemini Flash — **not** Cursor tokens.

## Out of scope (unless explicitly asked)

- LoRA merge → GGUF on production ladder (export/train scripts shipped; GPU merge is manual)
- ChatRouter backend Cursor integration
- Blossom Companion UI changes
```

---

*End of MustDo.md*
