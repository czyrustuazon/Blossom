# Handoff — Blossom Assistant refactor training ("Dr. Light" loop)

**Status (2026-11-20, second session): DONE CRITERION MET.** Cycle 9 = 5/5, confirmation
cycle 10 = 4/5. Caveat: passes still lean on host recovery (cycle 10 tool failures:
cjs-to-esm 25, globals-to-di 18, split-module 11 — mostly malformed JSON), so the
next step is reliability (see "Next: hardening" below), not more one-off patches.
The second-session changes are **NOT committed yet**. Earlier work is committed:
Blossom `e3ebef8` and Blossom Assistant `839fda9`.

Full technical record of the session (architecture of the loops, cycle-by-cycle
findings, every correction and why): [`tools/eval/TRAINING.md`](tools/eval/TRAINING.md).

## The goal

The user wants Blossom Assistant (the VS Code extension → Assistant ChatRouter on
`:8083` → local Nemotron 3.5 Lightning 30B coder) to handle **whole-project
refactors**, not single-file edits. The method, in the spirit of Dr. Light's
morality testing of X: give Blossom a task, grade its output and its reasoning,
correct what it is shown and told, then run it again. Stop when results are
acceptable.

**Done means:** all 5 tasks in `project-refactor` pass in one cycle, then a
second clean confirmation run passes too (≥4/5 at minimum).

"Training" here means prompts, rules, retrieved memory and host-loop behavior.
No model weights are changed. LoRA is a separate pipeline under `tools/lora/`;
leave it alone.

## Where things stand

| Cycle | Score | Notes |
|-------|-------|-------|
| 0 (baseline) | 0/5 | Never edited a file. Wrote fake ```` ```bash read_file x ```` "tool calls". Its own broken replies were stored and retrieved as "Working solution" lessons, next to NLPP romhack bans and PowerShell docs. |
| 1 | 0/5 | Real multi-file edits appeared. Failure modes: stopping after the plan, re-reading the same files, lost malformed calls. |
| 2, 3 | not scored | Stopped early once the lesson was clear (diagnostics only). Cycle 3: `extract-helpers` reached green tests but was never scored. |
| 4 | interrupted | Paused at `cjs-to-esm` round 7, at the user's request. |

| 5 | 3/5 | First passes. rename-symbol looped on a leftover hit; split-module lost a tool call and never ran tests. |
| 6 | 4/5 | rename-symbol passes. split-module deleted its source module while the replacement writes were malformed, then rewrote it from memory. |
| 7 | 3/5 | Passing tasks finish in 7–10 rounds (were 13–16). Double-escaped code; blind test edits. |
| 8 | 2/5 | Fabricated "### Summary … All tests pass" with zero tool calls; missing `}`; two bare tool_call lines lost one. |
| 9 | **5/5** | First clean sweep. |
| 10 | **4/5** | Confirmation. rename-symbol hit max rounds; many recovered malformed calls. |

### Next: hardening (recommended order)

1. **Native tool calls / constrained JSON.** llama-server already runs with `--jinja`
   (`LlamaServerManager.py`), so OpenAI `tools` or a JSON-schema/grammar on agent
   rounds is available; ChatRouter does not use it. Probe Nemotron 3.5's template first.
2. **Host-run tests** after every edit round (test command from package.json / pytest).
3. **Re-sample a round once** when it has malformed calls, before reporting an error.
4. **Writes as path fences only** (no code inside JSON strings).
5. **Measure with N=3 runs per task** + 2–3 new tasks (PHP modernization) to avoid overfitting five tasks.
6. LoRA on the clean trajectories in the run logs — only with the user's approval.

### Second session (uncommitted) — every fix is in BOTH `agent_loop.py` and the extension

Items 15–18 (cycles 7–8): double-escape decode (`undoDoubleEscape`), stray `)` and
missing-`}` repair (`balanceBraces`), every fence closed before the next opener,
edit-rounds-without-test nudge, exact `search_replace` templates for repeated hits
(`editTemplates`), fabricated-summary push (`claimsUnrunWork`), eval host allows
`;`/`|` inside quotes.

Each fix has a regression test in `test_agent_loop.py` (39 pass) built from
Blossom's real output; the extension side was checked by compiling to a scratch
dir and running `toolProtocol.js` in node with a stub `vscode` module.

1. **Read before overwrite.** `write_file` on an existing file is refused unless
   it was read in an EARLIER round or written by the coder itself (cycle 4
   package.json guess). Extension: `unreadOverwriteRefusal` + `workspaceFileExists`.
2. **`npm test 2>&1`** allowed in the eval host (trailing stderr merge only).
3. **Own writes stay in view.** A whole-file write is shown in the working set as
   the file's current content (cycle 5: "I don't know the current contents" → re-read all).
4. **Bare-quote JSON repair** (`repairUnescapedQuotes`): a `"` that cannot end a
   string is escaped (cycle 5 regex code in JSON).
5. **Missing opening fence** (`tool_call\n{…}```) is parsed (`normalizeToolFences`).
6. **Verify push:** finishing with edits and no passing test since → one push to run tests.
7. **Leftover quoting:** tests green + searches since still hit → host lists the
   hits AND the empty searches and forces "fix or finish".
8. **Repeated empty search** flagged ("nothing left for that query").
9. **Stale prose dropped** once tests pass after the last edit.
10. **Verified-idle cut-off:** green + 2 rounds of check-only calls → those calls
    are not run, summary demanded; a second such round ends the task. Edits still run.
11. **Deleted file's last read kept** in the working set, labeled DELETED.
12. **Deletes run last and are skipped if an edit in the same reply failed.**
13. **Extension bug fixed:** `findMalformedToolCallFences` looped forever (the
    parser reset the shared global regex's `lastIndex`). Any rebuild of `839fda9`
    would have hung on the first tool call.
14. `coding_rules.txt`: never write an unread file; no generator scripts;
    one command per run_command; `python` not `python3`.

## How to run a cycle

All commands are PowerShell, run from the repo root.

**1. Check the capsule is still valid** (no model needed):

```powershell
cd tools\eval
python run_eval.py run --corpus project-refactor --reference --db $env:TEMP\capsule.db   # expect 5/5 PASS
python run_eval.py run --corpus project-refactor --dry-run   --db $env:TEMP\capsule.db   # expect acceptance FAIL x5
python -m pytest -q -p no:cacheprovider test_agent_loop.py test_eval_harness.py         # expect all pass
```

**2. Start an isolated test router.** Never evaluate against the real `:8083`:
ChatRouter auto-saves coder answers into `coding_lessons`, and test runs would
write into Blossom's real memory.

```powershell
$S = "<any scratch folder>"
robocopy Mind\assistant "$S\capsule-mind\assistant" /E      # ~2.6 GB copy of the Assistant Mind
$env:BLOSSOM_MIND_ROOT = "$S\capsule-mind"
$env:BLOSSOM_SURFACE = "assistant"
$env:BLOSSOM_ROUTER_PORT = "8093"
$env:BLOSSOM_BRAIN_BROKER_URL = "http://127.0.0.1:8085"
$env:EVAL_ON_STARTUP = "false"
Start-Process python -ArgumentList "PythonScripts\ChatRouter.py" -WorkingDirectory PythonScripts -WindowStyle Hidden `
  -RedirectStandardError "$S\capsule-router.log" -RedirectStandardOutput "$S\capsule-router.out.log"
# Wait for "Uvicorn running" in capsule-router.log
```

The router binds to `CHAT_ROUTER_HOST` from `PythonScripts/.env` (the Tailscale
address, not 127.0.0.1). Never commit that IP.

**3. Run the cycle:**

```powershell
$env:BLOSSOM_EVAL_CHAT_URL = "http://<CHAT_ROUTER_HOST>:8093"
$env:PYTHONUNBUFFERED = "1"
cd tools\eval
python run_eval.py run --corpus project-refactor --db "$S\capsule-results.db" --log-dir "$S\runs\cycleN"
```

Each task logs one line per round (time, tool calls, fence writes).
`--log-dir` saves every round's full prompt and reply (router steps + model
reasoning + answer) plus `transcript.json`. Grade from those files, not just
pass/fail. The `process` check reports `researched_first`,
`ran_tests_after_last_edit`, `verified_green`, `tool_failures` and
`unverified_success_claim`.

**4. Evaluate, correct, repeat.** Find the first round where it went wrong and
read the reasoning, not only the visible reply. Then decide which kind of fix
it needs:

- **What it is shown:** prompt assembly, retrieval, transcript → ChatRouter / SemanticMemory / toolProtocol.ts
- **What it is told:** `PythonScripts/coding_rules.txt`. Re-read on every request, so no restart needed.
- **What the host does with its output:** parsing, repair, feedback → `agent_loop.py` **and** the extension, kept in sync

Add a regression test to `test_agent_loop.py` for every parser or host
behavior you fix, using Blossom's real failing output.

## The capsule

| Path | What it is |
|------|------------|
| `tools/eval/corpora/project-refactor/tasks/<id>/project/` | Starting project copied into the work dir |
| `.../hidden/` | Acceptance tests the model never sees; copied in as `_acceptance/` only for scoring |
| `.../reference/` | Known-good solution (+ `_delete.txt`) used by `--reference` |
| `tools/eval/blossom_eval/agent_loop.py` | Headless replica of the extension's ChatRouter tool loop: same fence protocol, `[AGENT LOOP]`/`[CONTINUE]` blocks, transcript, research status. Path fences are applied like Apply. `run_command` is allowlisted. |
| `tools/eval/blossom_eval/harness.py` | `mode: agent` → `run_agent_task`, `process_metrics`, `_apply_reference` |
| `tools/eval/test_agent_loop.py` | Regression tests built from Blossom's real malformed calls |

The five tasks: `rename-symbol` (rename across package, tests, README),
`extract-helpers` (deduplicate into `textutil.py`), `split-module` (god module
→ package with `__main__`), `globals-to-di` (global settings → injected
classes, an API change), `cjs-to-esm` (Node CommonJS → ESM).

## Corrections already made (committed in `e3ebef8` / `839fda9`)

Each fix below came from a failure seen in the transcripts.

**`PythonScripts/ChatRouter.py`**
- `_is_agent_round()`: on agent rounds, skip the task brief ("one fence per
  file"), the `FILE_EDIT_OUTPUT_CONTRACT`, the "Do it now" push and auto-learn.
- `_looks_nlpp()` gates NLPP hard bans. `_coding_rules_text(nlpp=...)` appends
  `nlpp_rules.txt` only for NLPP / 3DS work.
- `CRAWL_MAX_DISTANCE` (0.45): crawled docs farther than this are dropped. The
  crawl corpus is mostly PowerShell/Azure/ffmpeg pages, which matched Python
  and JS refactors at 0.53–0.77.
- Agent stall push: a reply with intent prose or an unlabeled code dump, and
  no tool call or path fence, gets one "emit the tool calls now" follow-up.
  `_AGENT_WRAPUP_RE` exempts real wrap-ups.
- `_strip_think_debris()` removes leaked ```` ```</think> ```` lines.
- `CODER_AGENT_TEMPERATURE` (0.6) via `_AGENT_ROUND_CV`. Nemotron at 1.0
  produced malformed JSON and `</think>` loops.
- The "cut off inside a code block" continuation runs on agent rounds only
  when `finish_reason == "length"`. Tool-call JSON had triggered it falsely,
  costing about 9 minutes per round.

**`PythonScripts/SemanticMemory.py`**
- `looks_like_broken_agent_output()`: rejected by `learn_coding_lesson` and
  filtered out in `query_coding_lessons`. This protects the real store, which
  already holds poisoned lessons, without deleting anything.

**`PythonScripts/coding_rules.txt`** (+ new `nlpp_rules.txt`)
- TOOL CALL FORMAT section, with the wrong ```` ```bash ```` form shown.
- `search_text` is literal, not regex.
- "A plan does nothing; only tool calls change files."
- Use path fences for code containing quotes, backticks or backslashes.
- WHOLE-PROJECT REFACTOR PLAYBOOK: inventory → plan every file → execute →
  search again for leftovers → run tests → debug from the error message.
- Node ESM needs the `.js` extension on relative imports.

**Extension `C:\Users\Zepse\Documents\Blossom Assistant\src\agent\`** (needs rebuild + reinstall to take effect)
- `toolProtocol.ts`:
  - `formatToolTranscript` keeps every result from the latest round, plus a
    **working set**: the latest unchanged read of each file and the latest
    result of each command, shown verbatim within a 40k-character budget.
  - `buildResearchStatus` adds host notes covering:
    - files already read (do not re-read them);
    - re-reads with no edit in between (execute now);
    - a repeated search with no edits (quotes the earlier hits back);
    - the same edit failing twice (send the whole file as a path fence);
    - tests green after the last edit (finish now).
  - `repairJsonEscapes`: escape-pair aware. Drops `` \` `` `\'` `\$`, doubles
    other invalid escapes.
  - Tolerates trailing `}` and a dangling `,"` at the end of a call.
  - `findMalformedToolCallFences` reports calls it could not parse.
- `orchestrator.ts`:
  - stores `read_file` bodies uncompacted (16k cap), since head/tail
    compaction hid the middle of files;
  - reports malformed calls back to the model and keeps the loop going if
    they were the only calls in the round.
- `tools.ts`: the `write_file` description points to path fences for code
  with quotes.

## Gotchas

- **Concurrent session.** Another agent commits to the same files: it made
  commits `eea7e76` and `7bc4b99`, the second removing the cloud fallback.
  Before editing, run `git status` / `git diff`. When committing, **stage only
  your own hunks** (`git add -p`). Work on the current branch: no new branches
  (user's global rule). Ask the user before committing.
- **Router restarts.** `coding_rules.txt` reloads on every request; Python
  changes need a test-router restart. A restart makes the broker swap
  llama-server to the persona model, and the next coding request swaps the
  coder back.
- **GPU contention.** If another GPU app is running when the coder loads (the
  user's "Instagram Model AI" did this), llama-server spills to the CPU and
  rounds take 5–10× longer. Check the free VRAM in the broker log's
  `Starting llama-server role=coder` line; it should be ~22 GB. Reload after
  the other app exits.
- **Interrupting a run.** If you kill the test router in the middle of a
  request, wait for the broker lease to free (`GET :8085/health` →
  `lease.holder` null) before restarting.
- **Real Mind.** Never write to `Mind/assistant` from evals. Seeding good
  lessons into it is a separate step that needs the user's approval.
- **Knowledge gap.** Blossom believed "Node adds .js automatically" for ESM.
  Watch for confident factual errors in its reasoning, not just protocol
  slips.

## After 5/5

1. Run a confirmation cycle. Consider adding 1–2 harder tasks (e.g. PHP
   modernization across files, which mirrors the user's real request
   "refactor the php code in here to be more compliant to modern 2026
   standard"; it needs `php` on PATH).
2. Rebuild and reinstall the extension (`compile.bat`, then package and
   install the `.vsix`). Smoke-test one refactor in real VS Code.
3. Ask the user whether to commit (own hunks only) and whether to seed a few
   verified refactor lessons into the real `coding_lessons`.
