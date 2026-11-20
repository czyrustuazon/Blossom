# Refactor training: technical record

Technical record of the first training session, 2026-11-20. The goal: teach
Blossom Assistant to refactor **whole projects** (not single files) through
cycles of *give it a task → grade output and reasoning → correct → repeat*,
the way Dr. Light tested X before releasing him.

- What to do next: [`handoff.md`](../../handoff.md)
- Commits: Blossom `e3ebef8`, `1acd2cb`; Blossom Assistant `839fda9`

---

## 1. What "training" means here

No model weights change. The coder (Nemotron 3.5 Lightning 30B-A3B, IQ4_XS,
64k context) is fixed. What we train is **everything around it**:

| Lever | Where | Takes effect |
|-------|-------|--------------|
| What it is **told** | `PythonScripts/coding_rules.txt`, `nlpp_rules.txt` | Next request (re-read from disk every call) |
| What it is **shown** | ChatRouter prompt assembly; SemanticMemory retrieval; the extension's transcript packing | Router restart / extension rebuild |
| What the **host does with its output** | Tool-call parsing, repair, error feedback, loop control (`toolProtocol.ts`, `orchestrator.ts`; mirrored in `agent_loop.py`) | Extension rebuild |
| What it **remembers** | Chroma `coding_lessons` (RAG) | Immediately, which is why evals run against a copy |

LoRA (`tools/lora/`) is a separate, later option and was not used.

---

## 2. Where the loops run

There are **two nested loops**:

- **Outer loop (training cycle).** Run the corpus, read the transcripts, apply
  a correction, run again. A human or an agent drives it.
- **Inner loop (Blossom's agent turn).** Rounds of tool calls inside one task,
  the same loop the VS Code extension runs.

```
 ┌──────────────────────── OUTER LOOP: training cycle (manual / agent) ────────────────────────┐
 │                                                                                              │
 │  python tools/eval/run_eval.py run --corpus project-refactor --log-dir <runs>/cycleN         │
 │        │                                                                                     │
 │        │  for each task:                                                                     │
 │        │    copy tasks/<id>/project/ → temp work dir                                         │
 │        ▼                                                                                     │
 │  ┌──────────── INNER LOOP: blossom_eval/agent_loop.py (replica of the extension) ────────┐  │
 │  │ round N:  packed prompt = [USER REQUEST] + [REPO KNOWLEDGE] + [AVAILABLE TOOLS]        │  │
 │  │                         + [AGENT TOOL TRANSCRIPT] + [CONTINUE] + [RESEARCH STATUS]     │  │
 │  │        │ POST /v1/chat/completions (blossom_tier=full)                                 │  │
 │  │        ▼                                                                               │  │
 │  │   test ChatRouter :8093 ──lease──► BrainBroker :8085 ──► llama-server :11434 (coder)   │  │
 │  │   (BLOSSOM_MIND_ROOT = scratch copy of Mind/assistant)                                 │  │
 │  │        │ reply: ```tool_call fences / path fences / prose                              │  │
 │  │        ▼                                                                               │  │
 │  │   run tools in the work dir (read/search/edit/delete/run_command allowlist)           │  │
 │  │   apply path fences like the extension's Apply step                                   │  │
 │  │   no tool calls → turn ends;  else next round (max 16)                                │  │
 │  └────────────────────────────────────────────────────────────────────────────────────────┘  │
 │        │                                                                                     │
 │        ▼  copy tasks/<id>/hidden/ → work dir/_acceptance/                                    │
 │   score: visible tests + hidden acceptance tests + process metrics → SQLite results DB      │
 │        │                                                                                     │
 │        ▼  read round-NN.prompt.md / round-NN.reply.md (router steps + reasoning + answer)    │
 │   diagnose first wrong round → correct rules / router / host → next cycle                   │
 └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Processes and ports

| Component | Address | Role in training |
|-----------|---------|------------------|
| Real Companion router | `<CHAT_ROUTER_HOST>:8081` | Untouched |
| Real Assistant router | `<CHAT_ROUTER_HOST>:8083` | Untouched: **never evaluate here**, it auto-learns into the real Mind |
| **Test router** | `<CHAT_ROUTER_HOST>:8093` | Separate ChatRouter process: `BLOSSOM_SURFACE=assistant`, `BLOSSOM_MIND_ROOT=<scratch>/capsule-mind`, `EVAL_ON_STARTUP=false` |
| BrainBroker | `127.0.0.1:8085` | Shared. Hands out exclusive llama-server leases, so test and real traffic serialize |
| llama-server | `127.0.0.1:11434` | Shared coder (or persona after a swap) |

`<CHAT_ROUTER_HOST>` is the Tailscale address from `PythonScripts/.env`.
Don't commit it.

### Files and data

| What | Path | Persistent? |
|------|------|-------------|
| Corpus | `tools/eval/corpora/project-refactor/` | Yes (repo) |
| Inner-loop replica | `tools/eval/blossom_eval/agent_loop.py` | Yes |
| Agent-mode harness | `tools/eval/blossom_eval/harness.py` (`run_agent_task`, `process_metrics`, `_apply_reference`) | Yes |
| Regression tests | `tools/eval/test_agent_loop.py` | Yes |
| Isolated Mind copy | `<scratch>/capsule-mind/assistant` (~2.6 GB) | No, recreate with robocopy |
| Round logs | `<scratch>/runs/cycleN/<task>/round-NN.{prompt,reply}.md`, `transcript.json` | No |
| Results DB | `--db` path (default `Mind/eval_results.db`; this session used a scratch DB) | Depends |

The 2026-11-20 run logs live in the Claude Code session scratchpad and may
already be gone. The findings they produced are recorded in §5.

---

## 3. The corpus

Five small but genuinely multi-file projects. Each task folder has:

- `project/`: starting code, with its own visible tests (passing at start)
- `hidden/`: acceptance tests the model never sees; they check the refactor
  goal (old name gone, helpers defined once, package layout, no `global`, ESM)
- `reference/`: a hand-written correct solution, plus `_delete.txt`

| Task | Language | What it tests |
|------|----------|---------------|
| `rename-symbol` | Python | Rename across definition, aliased imports, `module.fn` calls, `__all__`, tests, README; no alias left |
| `extract-helpers` | Python | Deduplicate copy-pasted helpers into `textutil.py`; every module imports it; one definition each |
| `split-module` | Python | God module → package (`models/storage/reports/cli`), re-exports, `__main__.py`, delete the old `.py` |
| `globals-to-di` | Python | Global settings dict and `global` statements → `Settings` dataclass + constructor injection; an API change, so tests must be updated |
| `cjs-to-esm` | Node | CommonJS → ESM across src/ and test/, `"type": "module"`, `.js` extensions, same public API |

**Validity check:** the reference solutions pass 5/5. The untouched projects
fail acceptance 5/5 while their visible tests pass. A pass therefore means
the refactor really happened and behavior was preserved.

### Process metrics (the "reasoning" grade)

Each agent run also records `rounds`, `elapsed_sec`, `stop_reason`, `edits`,
`files_touched`, `researched_first`, `ran_tests_after_last_edit`,
`verified_green`, `tool_failures` and `unverified_success_claim` (claimed
passing tests without a green run).

---

## 4. Fidelity: how close the replica is to the real extension

`agent_loop.py` was ported from `toolProtocol.ts` / `orchestrator.ts`:

- one packed user message per round;
- ```` ```tool_call ```` JSON fences;
- the same `[AGENT LOOP]` / `[CONTINUE]` wording;
- the compact transcript;
- `blossom_tier=full`;
- path fences applied like Apply.

It also checked whether non-streaming requests take a different coder path:
they don't (both go through `_stream_local_chat`).

**Known gaps (the replica is a lower bound):**
- Extension-only rescues are not replicated: host search after a search
  monologue, pattern-scan continues, the local retry pass.
- `run_command` uses a stricter allowlist (no pipes or redirects). It wrongly
  refused `npm test 2>&1` in cycle 4. To do: allow a trailing `2>&1`.
- No `[EDITOR CONTEXT]` attachment, so the router's file-edit contract (which
  fires only when files are attached) was never exercised.
- No `DELETE path=` prose lines; deletes go through `delete_file` only.

---

## 5. Cycle log

| Cycle | Result | Rounds/task (typ.) | Headline |
|-------|--------|--------------------|----------|
| 0 | 0/5 | 1–4 | Never edited a file |
| 1 | 0/5 | 2–16 | First real multi-file edits; narrate-and-stop; re-read loops |
| 2 | stopped (diagnostic) | — | Edit → test → fix loops appear; JSON escaping breaks edits |
| 3 | stopped (diagnostic) | — | Green tests reached on `extract-helpers`; GPU contention; false continuations |
| 4 | interrupted at user request | — | Writes before reads; harness refused `2>&1` |

### Cycle 0: baseline

**Symptoms.** Replies ended within 2–4 seconds of generation. They held tool
names inside ```` ```bash ```` fences (`search_text query="calc_total"`) and
walls of ```` ```</think> ````. Zero edits.

**Root cause.** The full coder prompt was captured offline by importing
ChatRouter with the model call stubbed. For a Python rename it contained:

| Block | Size | Problem |
|-------|------|---------|
| Coding rules | 11 KB | Included the whole NLPP / 3DS constitution |
| Task brief | 0.7 KB | "one markdown fence PER file", which contradicts the tool loop |
| NLPP hard bans | ~2.5 KB | zlib splicing, LayeredFS, CIA bakes: irrelevant |
| Prior coding lessons | ~3 KB | **Its own broken replies from minutes earlier, stored as "Working solution"** |
| Crawled docs | ~1.5 KB | PowerShell `Update-ModuleManifest` (matched on "module" / "export") |

**Self-poisoning loop.** ChatRouter auto-learned every agent round. The only
gate was "has a complete code fence", which ```` ```bash list_dir ```` passes.
So broken output became a lesson, the lesson was retrieved, and the model
copied it. This also affects the real `Mind/assistant` store.

**Amnesia.** The transcript kept full bodies only for the last 2 entries
(`FULL_TRANSCRIPT_TAIL = 2`). A reply that read 6 files in parallel saw only 2
of them, so it re-read forever.

### Cycle 1

Real ```` ```tool_call ```` fences appeared, along with multi-file edits.
`rename-symbol` edited all 7 files; `extract-helpers` created `textutil.py` and
edited 4 modules. New failure modes:

- **Narrate-and-stop.** The reasoning worked out every converted file
  correctly, but the visible reply was "Let me convert all files…" with no
  calls, so the turn ended.
- **Re-research habit.** `split-module` knew `inventory.py` line by line (it
  listed the class ranges in its reasoning) yet re-read it for 9 rounds. The
  rules said "RESEARCH first" and nothing said research was done.
- **Lost edits.** Malformed JSON (`"__all__ = ["calc_total"]"` with unescaped
  quotes) was silently dropped by the extension. Those were exactly the edits
  the failing tests needed.
- **Collapse at temperature 1.0.** One final round degenerated into dozens of
  ```` ```</think> ```` lines.
- **Regex in a literal search.** `search_text` queries like
  `require\|module\.exports`, which are also invalid JSON escapes.

### Cycle 2 (diagnostic)

Edit → test → fix loops appeared (`extract-helpers` rounds 3–12). Failures:

- **Backtick escapes.** `` \` `` inside template literals is invalid JSON. The
  first repair attempt (doubling the backslash) would have written a literal
  `` \` `` into the JS; regression tests caught it, and the repair became
  escape-pair aware.
- **Repeated malformed calls.** It resent the same malformed call 10 rounds in
  a row, ignoring the "redo as a path fence" error.
- **Unread errors.** It didn't read the test error: `Cannot find module
  '../src/index'` led to more leftover searches instead of fixing the import.
- **Unlabeled code dump.** A bare fence with no `path=` can't be applied.
- **Circling.** Its reasoning named the exact remaining edits (README + one
  test function name), then searched for `calc_total` again, round after
  round.

### Cycle 3 (diagnostic)

- **False continuations.** The router's new "cut off inside a code block →
  continue" logic (from a concurrent session's commit `eea7e76`) misread
  tool-call JSON as an unclosed fence and ran 2 continuations, costing about
  561 seconds for one round.
- **GPU contention.** The router restart swapped llama-server to the persona
  model. Meanwhile another GPU app (Instagram Model AI) took VRAM, so the
  coder reloaded with 8.4 GB free instead of 22.4 GB. Its layers spilled to
  the CPU and rounds ran 5–10× slower.
- **Lost evidence.** The failing assertion (`' [ ] x' !== '[ ] x'`) collapsed
  into "exit 1" once later reads arrived, so it re-ran the tests just to see
  the error again.
- **A misfire in my own status check.** It flagged re-reads *after the model's
  own edits*, which are legitimate.
- **JSON slips that lost 8 valid edits in one round.** 5 had an extra closing
  brace `}}}`; 3 had a dangling `,"` before the braces.
- **Adapted within a turn.** After malformed calls were reported back, it
  switched to complete-file writes and reached green tests ("3 passed").
- **Over-verification.** With green tests and a clean leftover search, it
  kept re-running the tests for 7 rounds, because nothing said it was done.
- **Knowledge error in reasoning.** "Relative imports without `.js` also work
  (Node adds .js automatically)" is false for ESM.

### Cycle 4 (interrupted)

The coder was reloaded on the full GPU (~94 s for a large first round). Two
new issues showed before the pause:

- **Writes before reads.** Round 1 sent reads and writes in the same reply, so
  the writes were based on guesses. It overwrote `package.json` with invented
  content (`"name": "task-manager"`).
- **Refused command.** The harness refused `npm test 2>&1` (see §4).

---

## 6. Corrections and the failure each one answers

### ChatRouter (`PythonScripts/ChatRouter.py`)

| Change | Failure it answers |
|--------|--------------------|
| `_is_agent_round()`: skip task brief, `FILE_EDIT_OUTPUT_CONTRACT`, "Do it now" push and auto-learn on agent rounds | Contradictory format instructions; self-poisoning lessons |
| `_looks_nlpp()` gates NLPP hard bans; `_coding_rules_text(nlpp=…)` appends `nlpp_rules.txt` only for NLPP work | 3DS romhack rules steering a Python rename |
| `CRAWL_MAX_DISTANCE` = 0.45 | PowerShell / Azure / ffmpeg crawl hits at distance 0.53–0.77 for every query |
| Agent stall push (intent prose or unlabeled fence, no tool call, not a wrap-up) | Narrate-and-stop; unlabeled code dumps |
| `_strip_think_debris()` | ```` ```</think> ```` spam |
| `CODER_AGENT_TEMPERATURE` = 0.6 via `_AGENT_ROUND_CV` (plain coding keeps 1.0) | Malformed JSON and collapse at temperature 1.0 |
| No fence continuation on agent rounds unless `finish_reason == "length"` | 9-minute false continuations |

### Memory (`PythonScripts/SemanticMemory.py`)

| Change | Failure it answers |
|--------|--------------------|
| `looks_like_broken_agent_output()` blocks learning and filters retrieval | Poisoned lessons, including ones already in the real store; nothing is deleted |

### Rules (`PythonScripts/coding_rules.txt`)

| Section | Failure it answers |
|---------|--------------------|
| TOOL CALL FORMAT (right vs. wrong examples) | ```` ```bash ```` pseudo-calls |
| Literal `search_text`; "a plan does nothing" | Regex queries; narrate-and-stop |
| Path fences for code with quotes / backticks | Unescaped JSON edits |
| WHOLE-PROJECT REFACTOR PLAYBOOK: inventory → plan every file → execute → search for leftovers → test → debug from the error | Missed callers; re-searching instead of fixing |
| Node ESM `.js` rule | Wrong belief about Node ESM resolution |

### Host loop (extension `toolProtocol.ts`, `orchestrator.ts`, `tools.ts`; mirrored in `agent_loop.py`)

| Change | Failure it answers |
|--------|--------------------|
| All results of the latest round kept in full | 6 parallel reads → 2 visible |
| Working set: latest unchanged read per file (verbatim, 40k budget) + latest result per command; `read_file` stored uncompacted (16k cap) | Re-read loops; head/tail compaction hiding the middle of files; lost test errors |
| `[RESEARCH STATUS]` host block covering already-read files, unchanged re-reads, a repeated search (quoting its hits), a repeated failed edit (send the whole file), and VERIFIED (finish now) | Re-research habit; circling; resending malformed calls; over-verification |
| `repairJsonEscapes` (pair-aware), trailing `}` trim, dangling `,"` fix | Lost edits: 8 of 8 in the cycle-3 sample recovered |
| `findMalformedToolCallFences` reported as failed calls; the loop continues | Silent edit loss |
| `write_file` description points to path fences | Repeated JSON-escape failures |

Regression tests in `test_agent_loop.py` (13) use Blossom's real failing
output.

---

## 7. Environment lessons

- **Isolate memory.** Real routers learn from every coding answer; always
  evaluate on a Mind copy.
- **Router restarts cost model swaps.** Startup bootstraps the persona model,
  and the first coding request swaps the coder back. Restart the test router
  only when ChatRouter code changes. Rules changes are live.
- **Check VRAM at load time.** The broker log's `Starting llama-server
  role=coder … free N MiB` should show about 22 GB. If another GPU app was
  running at load, reload the coder after it exits.
- **Leases.** Killing a router mid-request leaves a lease until it expires.
  Wait for `GET :8085/health` → `lease.holder: null`.
- **Concurrent sessions.** Another agent was committing to ChatRouter,
  SemanticMemory and the rules during this session (`eea7e76`, `7bc4b99`).
  Check diffs before editing, and stage only your own hunks.

---

## 8. Reproduce a cycle

```powershell
# 0. capsule sanity (no model)
cd tools\eval
python run_eval.py run --corpus project-refactor --reference --db $env:TEMP\c.db   # 5/5
python -m pytest -q -p no:cacheprovider test_agent_loop.py test_eval_harness.py

# 1. isolated test router
$S = "<scratch>"
robocopy ..\..\Mind\assistant "$S\capsule-mind\assistant" /E
$env:BLOSSOM_MIND_ROOT="$S\capsule-mind"; $env:BLOSSOM_SURFACE="assistant"
$env:BLOSSOM_ROUTER_PORT="8093"; $env:BLOSSOM_BRAIN_BROKER_URL="http://127.0.0.1:8085"
$env:EVAL_ON_STARTUP="false"
Start-Process python -ArgumentList "..\..\PythonScripts\ChatRouter.py" -WorkingDirectory ..\..\PythonScripts `
  -WindowStyle Hidden -RedirectStandardError "$S\capsule-router.log" -RedirectStandardOutput "$S\router.out.log"

# 2. one cycle
$env:BLOSSOM_EVAL_CHAT_URL="http://<CHAT_ROUTER_HOST>:8093"; $env:PYTHONUNBUFFERED="1"
python run_eval.py run --corpus project-refactor --db "$S\results.db" --log-dir "$S\runs\cycleN"
```

Per-round timeout: `BLOSSOM_EVAL_ROUND_TIMEOUT` (default 2400 s). Per-task
round cap: `max_rounds` in `task.json` (default 16).

---

## 9. Open items

1. Host check plus rule: never `write_file` an existing path that has no
   successful `read_file` this turn (cycle-4 `package.json` overwrite).
2. Allow a trailing `2>&1` in the harness's `run_command`.
3. Run cycles until 5/5, then a confirmation run.
4. Rebuild and reinstall the extension; smoke-test a real refactor in VS Code.
5. Optionally add a multi-file PHP modernization task, which mirrors the
   user's real request; it needs `php` on PATH.
6. With the user's approval, seed verified refactor lessons into the real
   `coding_lessons`, and decide whether to purge the poisoned ones (currently
   only filtered).
