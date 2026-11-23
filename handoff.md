# Handoff — Blossom Assistant refactor training ("Dr. Light" loop)

**Status (2026-11-20, second session): DONE CRITERION MET.** Cycle 9 = 5/5, confirmation
cycle 10 = 4/5. Caveat: passes still lean on host recovery (cycle 10 tool failures:
cjs-to-esm 25, globals-to-di 18, split-module 11 — mostly malformed JSON), so the
next step is reliability (see "Next: hardening" below), not more one-off patches.
Committed: Blossom `738417b`, Blossom Assistant `e016c00` (earlier: `e3ebef8` / `839fda9`).
**Third part of the session (committed: Blossom `1c0efea`, Blossom Assistant `e05f643`):**
native tool calls implemented and A/B-tested — fence 11/15 vs native 10/15 over 3
alternating cycles each, so no measured gain; native is opt-in (off).
**Fourth part (committed: Blossom `cf10a07`, eval loop):** the host runs the project's tests
after every edit round. A/B, fence mode, alternating: host tests ON 4, 5, 5 (14/15);
OFF 4, 3, 4 (11/15). First change that clearly moved the pass rate (3 cycles each; small sample).
**Fifth part (2026-11-21, extension, committed Blossom Assistant `dbd4fb4`, built and
installed as 0.1.67 in Cursor and VS Code):** host-run tests mirrored into
Blossom Assistant. `toolProtocol.ts`: `isTestCommand`, `pickTestCommand`,
`shouldHostRunTests`, `HOST_TEST_NOTE`; `tools.ts`: `detectWorkspaceTestCommand` (primary
root: package.json test script, else `test_*.py`/`*_test.py` in `.`, `tests/`, `test/`);
`orchestrator.ts`: `deliverPendingEdit` now returns whether it applied; after a ChatRouter
tool round with ≥1 applied edit, NO edit left waiting for Apply, and no test command from
the coder, the host runs the test command through `confirmRunCommand` (so
`commands.askBeforeRun` / allowlist / fast mode apply) and pushes a `run_command` entry with
`by: "host"` + `HOST_TEST_NOTE`. A Deny turns it off for the rest of the turn. Setting
`blossom.agent.hostRunsTests` (default on). `tsc --noEmit` clean; helpers checked in node
with a stub `vscode`. Differences from the eval: path-fence-only rounds (no tool calls) do
not trigger it, and a red host test does not need the "keep the turn going" rule because
tool rounds always continue.
**Sixth part (2026-11-21, committed: Blossom `194878c`, Blossom Assistant `c32ce25`, built
and installed as 0.1.67 in Cursor and VS Code):** host checks on the coder's own edits,
three new tasks (corpus is now 8), an A/B runner, and a timeout that kills the whole
process tree. A/B over 8 tasks, 3 alternating cycles each: **hardening ON 19/24 (7, 6, 6),
OFF 15/24 (4, 6, 5)**. Details in "Sixth part" below.

**Seventh part (2026-11-21 evening) — the eval now runs through the REAL extension.**
The replica (`agent_loop.py`) scored well while the user's VS Code Blossom made no edits at
all: they had drifted apart. Running the real extension found the main cause in ChatRouter
(below). Real extension, 4 tasks × 2 cycles: **0/4 before the router fix → 5/8 after.**
Committed: Blossom Assistant `883c00b` (installed as 0.1.79 in VS Code), Blossom (this commit).
Details: "Seventh part" section below.

**Eighth part (2026-11-22, uncommitted, NOT yet measured):** four general fixes, built as
Blossom Assistant 0.1.82 (`.vsix` packaged, not installed). The stack was down after a reboot
and the GPU held ~9 GB for other apps, so no eval ran.
- **Zero-edit finish guard** (extension `orchestrator.ts` + `promptTier.ts::asksForChange`): a
  change request whose turn is about to end with no edit attempted (no write/replace/delete,
  no path fence) and no question to the user gets one `[HOST — the requested change has not
  been made]` push ("passing tests only show the OLD code still works"). `asksForChange`
  covers all 9 corpus prompts (convert/replace/extract/turn it into…) and rejects
  look/explain/report-only asks — `npm run test:prompt-tier`.
- **README listed twice** in repo knowledge (Windows opens `README.md` and `readme.md` as one
  file): only the first one found is used (`repoKnowledge.ts`).
- **Poisoned coding lessons** (`SemanticMemory.py::looks_like_non_solution`, write + read
  side, nothing deleted): answers that ask the user to share/paste files, say they cannot see
  the code, end on intent only ("Let me start by examining…") with no code block, or open an
  empty fence before a `path=` label. Real store audit (copy of `Mind/assistant`, 50 lessons):
  all 5 auto-learned lessons are answers to the user's own PHP refactor asks; 4 are now hidden,
  the 44 NLPP seeds and the `add()` lesson are kept. Lesson #46 (declines to replace `mysql_*`
  as "beyond minimal edits", missing `;`) still looks like code — deleting it from the real
  store needs the user's OK. Tests: `PythonScripts/test_coding_lessons.py` (from the real texts).
- **Lesson review queue (user's request):** `learn_coding_lesson` no longer writes to Chroma;
  it queues the lesson in `Mind/assistant/lesson_queue.db` (`LessonQueue.py`) and returns
  `queued:<id>`. Review with `python PythonScripts/review_lessons.py` (`list`, `show <id>`,
  `approve <id>…`, `reject <id>… --reason`); `list` flags NON-ANSWER / USER-VERIFIED. 👍 on a
  queued answer marks it user-verified (still pending), 👎 rejects it; the user's own 👎
  correction notes (coding_caution) are still stored directly. Companion still cannot write
  coding lessons. `LESSON_QUEUE=0` = old direct writes. `/v1/memory/coding` answers
  `queued: true`; the extension shows "Coding lesson queued for review". Tests:
  `PythonScripts/test_lesson_queue.py`. Evals no longer add lessons to the capsule either.
- **package.json mojibake fixed** (13 `â€”`/`â†’` spots in setting descriptions, committed since
  ~7 commits back); no BOM, CRLF kept.
- **Round cap** needs no code: measure with `--set blossom.agent.maxToolRounds=16` vs default 11.

**Next:** install 0.1.82, start broker + test router on :8093 (fresh capsule copy), run the
9-task baseline, then alternating A/B cycles: (a) 0.1.82 vs the 6/9 result, (b) round cap 16
vs 11. Restart the test router (and the user's :8083) to load the SemanticMemory change.

**START HERE next session:**
1. `git status` in both repos. Ask the user before committing. Leave
   `Mind/llama-server.model` unstaged in Blossom. Never rewrite repo files with PowerShell
   `Set-Content`/`Get-Content` (adds a BOM and mojibake to package.json — happened twice);
   edit bytes with Python or the Edit tool and check `git diff --stat`.
2. Evaluate through the real extension, not the replica:
   `python tools/eval/run_vscode.py --task <id> --runs N --name <arm> --out <dir>
   [--set blossom.agent.leanPrompt=true]` with `BLOSSOM_EVAL_CHAT_URL` = the test router
   (:8093). It opens a VS Code window per task (parent folder
   `Documents\blossom-eval-runs`, trusted), sends the prompt through the chat panel, auto-
   answers prompts (plan card → Approve), saves `trace.log`, `summary.json`, `score.json`
   and `round-NN.md` (full prompt + router steps + reasoning + reply per round), closes it.
   Read the round files before theorizing.
3. The user must restart their own ChatRouter (:8083) to get today's router fixes; only the
   test router (:8093) was restarted. A 9-task real-extension run on 0.1.79 was started at
   the end of the session (results not recorded here — rerun it).
4. Next levers (all general, measure each with alternating cycles):
   - `dict-to-dataclass` runs out of rounds (13–15) one test short: raise the full-tier
     round cap (replica used 16) and measure.
   - Prompt diet for the FULL prompt by section (lean as a whole lost 2/8 vs 5/8 — find
     which sections matter instead of dropping all; lean also drops the plan-tier rules).
   - Router still appends retrieved coding lessons that include the coder's own failed
     answers (it "learned" "please share the files" and copied it); audit auto-learn.
   - Repo knowledge lists README.md twice (readme.md) — case-insensitive dedupe.
5. User decisions that still hold: do NOT seed lessons into the real Mind ("hold off on
   seeding for now"). Big changes: plan → in-chat Approve card → same turn (user's choice).
   Claude and Gemini are no longer escalation options; only Cursor, asked in the chat.
6. Judge every change on 2–3+ alternating cycles, never on one: identical code still swings.

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
| 11 (2026-11-21, host tests on, fence) | 4/5 | rename-symbol: green after round 2, then its own `search_replace` turned `def test_calc_total_with_tax()` into `def test_compute_order_total_with_tax` (dropped `()`). It saw the SyntaxError (pytest + `ast.parse`) but read the line as valid for 12 rounds and rewrote the file twice with the same bug. Model error, not host repair. Idea: warn when a search_replace changes non-identifier characters (here `()`) in what looks like a rename. |

### Seventh part (2026-11-21 evening): real extension via debug MCP

**Why.** The user's real requests ("refactor this repo to be more modern and php compliant")
kept ending with no edits in VS Code while the replica passed most tasks. Two days of replica
fixes had not moved the real thing.

**Tooling (extension `src/debug/mcpServer.ts`, `src/agent/turnTrace.ts`).** Setting
`blossom.debug.mcpServer` (off by default) starts a JSON-RPC MCP server on 127.0.0.1:8790
(refuses requests with an Origin header; port +1..+9 if taken; URL written to
`~/.blossom/mcp/<workspace-hash>.json`). Tools: `blossom_send/wait/status/cancel/clear/
respond/close_window/info`, `blossom_trace` (Blossom Trace channel: streams with finish
reason and [DONE], agent rounds, statuses, tool results, edits, webview errors),
`blossom_rounds` (last 40 router exchanges in full), `blossom_last_prompt`, `blossom_tool`
(run any agent tool directly). Stall watchdog `blossom.agent.stallTimeoutSec` (240 s).

**Root causes found, in order of impact (all general, none task-specific):**
1. **ChatRouter dropped the agent loop.** `EditorContext.pack_editor_context` rebuilt any
   prompt containing `[EDITOR CONTEXT]` / `<<<FILE` as task brief + request + files, so
   every VS Code agent round lost its tool transcript, working set and host status. The
   coder re-read the attached files every round (12 identical rounds in one run). The
   replica never sends editor context, so it never saw this. Fix: agent rounds pass through
   untouched; over budget, only the file blocks are condensed in place
   (`test_editor_context.py`). Effect: 0/4 → 5/8.
2. **Plan-first gate.** `promptTier.ts` classes multi-file asks as plan-only ("ANSWER ONLY":
   no edits, host discards fences) and waits for a new "go ahead" message. Now the plan ends
   with an in-chat Approve / type changes / Cancel card that continues the same turn.
3. **Unknown tool names.** The coder calls `list_files`, `list`, `grep`, `cat`, passes
   `pattern` for `query`, `read_file "."`, `cwd: /workspace`. A bare "Unknown tool" for 5
   rounds led it to write a fake tool transcript and invent a project. `normalizeToolCall`
   in `tools.ts` maps these and tells the model what ran.
4. **Invented tool output written to disk.** Live fence apply took `system` and
   `**index.php:**` labels from a role-played transcript and wrote those files.
   `trustedReplyText` cuts a reply at host-only markers; bare-stem labels need a heading.
5. **read_file returned a 16-line "search window"** after any search hit unless a range was
   given — the coder re-read whole files for rounds. Range-less reads return the whole file.
6. Smaller: search-loop guard aborted healthy reasoning (looked like a freeze); path-fence
   edits did not count as edits (turn ended after one fence); `| head` / `|| true` hid
   failing exit codes; regex-shaped `search_text` queries now also run as regex; PHP syntax
   check (php -l or bracket balance); NLPP hard bans were injected into every coding task
   because the extension prompt mentions Ghidra (router now judges by ask + paths).

**Measured (real extension, test router, 2 cycles × 4 tasks, router fix in both arms):**

| Task | full prompt | lean prompt |
|------|-------------|-------------|
| callbacks-to-async | 2/2 | 0/2 |
| cjs-to-esm | 2/2 | 1/2 |
| dict-to-dataclass | 0/2 | 1/2 |
| extract-helpers | 1/2 | 0/2 |
| **Total** | **5/8** | **2/8** |

Lean (`blossom.agent.leanPrompt`, ~8k chars instead of ~45k) stays off.

**Corpus:** new task `php-modernize` (9 tasks now): a small mysql_*-era PHP site modelled on
the user's real project, prompt = the user's own words + "has to run on PHP 8.3", no visible
tests (the real project has none). Acceptance is static (php not installed): removed
functions, PDO/mysqli, no variables spliced into SQL, prepared statements, balanced syntax,
helpers and page inputs kept (`hidden/_php_scan.py`). `coding_rules.txt` gained a short
legacy-PHP section (PDO + placeholders, not a mysqli rename).

**9-task run, real extension 0.1.79/0.1.80 (1 run each): 6/9.** Pass: callbacks-to-async,
cjs-to-esm, dict-to-dataclass, print-to-logging, split-module (+ rename-symbol passed once
on 0.1.79, failed on 0.1.80). Fail: extract-helpers, globals-to-di, php-modernize (4 of 5
files converted, login.php left — ran out of rounds), rename-symbol.

**Decode loops (fixed after the 6/9 run).** An agent round repeated the same two tool
calls for 34k tokens / 138k chars: no max_tokens, the stall watchdog counts tokens as
activity, and the extension's Stop did not reach llama-server (ChatRouter does not abort the
upstream stream when the client disconnects — still open; restart the router to stop one).
Now: ChatRouter caps agent rounds at `CODER_AGENT_MAX_TOKENS` (16000) and closes the stream
when the last 400 chars already occur 6+ times in the last 12k; the extension has the same
guard, runs identical tool calls in one reply once, rejects non-path fence labels
(`</think>`), and parses `[tool_call name {json}]` lines (a final reply in that form had
ended a turn as "done").

**UI changes the user asked for:** live thinking as cards per step (grouped per round,
collapsing); reasoning updates throttled to 250 ms (spinner stutter came from re-sending
50k chars per token); escalation asked in the chat, Claude/Gemini removed (fallback chain and
handoff compression no longer call them).

### Sixth part (2026-11-21): host checks, 8 tasks, A/B runner

**Finding that shaped it.** The coder cannot see a missing `()`. In cycle 11 and again in
A/B run `rw-on2` its own rename edit wrote `def test_compute_order_total_with_tax:`. Told
"removed: ()", it answered "the colon was removed" and judged the line valid. A warning
alone does not fix this (rename-warning A/B on 5 tasks: on 14/15, off 12/15, but the warning
fired once and that run still failed — the gap is noise). So the host repairs it.

**Host checks** (`tools/eval/blossom_eval/host_checks.py`; extension:
`src/agent/hostChecks.ts`). Master switch `BLOSSOM_EVAL_HARDEN` (default 1); each check has
its own `BLOSSOM_EVAL_<NAME>`:

| Check | Switch | In extension |
|-------|--------|--------------|
| Syntax check after an edit (.py, .json, .js/.mjs/.cjs) | `SYNTAX_CHECK` | yes |
| Diff of everything changed since the tests last passed, shown on a regression; research status points at it first (`REGRESSION_MARKER`) | `GREEN_DIFF` | yes |
| Real closest text when a `search_replace` old_string is not found | `NEAR_MISS` | yes |
| Rename-shaped edit that drops punctuation: host restores it if the file then parses ("HOST FIX: …") | `PUNCT_REPAIR` | yes |
| Warning for the same case, punctuation spelled out in words | `RENAME_WARN` | yes |
| One re-ask when a reply has malformed tool calls; the reply with fewer is kept | `RESAMPLE` | no (eval only) |
| Unread overwrite is refused with the file's current content | `SHOW_UNREAD` | no (eval only) |

**Timeout fix.** `subprocess.run(shell=True, timeout=…)` killed only the shell; a hung
`npm test` (`node --test`) kept the pipe open and stalled cycle `off3` for 83 minutes.
Now `blossom_eval/proc.py::run_shell` (used by `t_run_command` and the scorer) and the
extension's `processTree.ts::killProcessTree` (foreground and background `run_command`)
kill the whole tree (`taskkill /T /F` on Windows) and bound the wait for the pipes.

**Corpus is 8 tasks**: added `print-to-logging`, `dict-to-dataclass`, `callbacks-to-async`.
All 8 references pass; a dry run fails all 8 on acceptance, as intended. No PHP task: PHP
is not installed here.

**A/B, all hardening on vs off** (8 tasks, 3 alternating cycles each):

| Task | ON | OFF |
|------|----|-----|
| callbacks-to-async | 3/3 | 2/3 |
| cjs-to-esm | 1/3 | 2/3 |
| dict-to-dataclass | 3/3 | 1/3 |
| extract-helpers | 2/3 | 3/3 |
| globals-to-di | 2/3 | 3/3 |
| print-to-logging | 3/3 | 2/3 |
| rename-symbol | 2/3 | 1/3 |
| split-module | 3/3 | 1/3 |
| **Total** | **19/24** | **15/24** |

Failed tool calls per task run: 1.8 on, 3.0 off. Notes shown in the ON arm: near-miss 22,
re-asked rounds 19, syntax error 3, regression diff 3, rename warning/repair 0. Caveats:
24 runs per arm is still a small sample; `off3` callbacks-to-async includes the 83-minute
hang (it passed anyway); the punctuation repair never fired in this A/B, so it is covered
by tests only.

**What still fails** (ON arm, 5 runs): four hit max rounds with red tests (`on2`
extract-helpers and globals-to-di, `on3` cjs-to-esm and rename-symbol), and `on1`
cjs-to-esm "finished" after 4 rounds with ZERO edits (ran the tests, saw green, stopped;
same in `off2` print-to-logging). Next lever: do not accept
"finished" when nothing was edited on a task that asks for a change.

**Tests:** `tools/eval`: `python -m pytest -q -p no:cacheprovider test_agent_loop.py
test_eval_harness.py test_host_checks.py test_proc.py` → 67 pass. Extension: 11
`npm run test:*` scripts pass (`test:host-checks` 9 checks, `test:host-tests` 15).

### Next: hardening (recommended order)

0. **Reject a zero-edit "finished"** (see "What still fails" above), in both hosts.

1. **Native tool calls.** llama-server already runs with `--jinja`
   (`LlamaServerManager.py`); ChatRouter does not pass `tools`. **Probed 2026-11-20
   (direct to llama-server, same sampling, "save this file verbatim" on escape-heavy
   code, 16 requests per mode):** native = a call in 15/16 requests, code intact every
   time, avg 14 s / 2.5k tokens. Fence protocol = 1/24 files correct even with all
   repairs, avg 50 s / 9.4k tokens, 9/16 replies burned the whole 12k-token budget
   reasoning about JSON escaping. Cause: Nemotron's template calls tools as
   `<tool_call><function=…><parameter=content>RAW TEXT</parameter>` (no escaping);
   the fence protocol forces code into JSON strings. Caveat: native emitted ONE call
   per reply (also with `parallel_tool_calls` and a system hint; one trial looped 82 calls).
   **Implemented 2026-11-20 (uncommitted), opt-in:**
   - Host sends OpenAI `tools` in the request. On agent rounds ChatRouter
     (`_stream_local_chat`) forwards them to llama-server and writes each parsed call
     back into the reply as a ```` ```tool_call ```` fence with valid JSON, marked
     `"native": true` (hosts skip their repairs for those; backticks are `\u0060`).
   - One call per reply → the router answers each call "Queued…" and asks for the
     next, up to `CODER_NATIVE_BATCH_MAX` (6) per host round; stops after
     `run_command` / `ask_user`.
   - Switches: `CODER_NATIVE_TOOLS` (router, default on, only acts when the host sends
     `tools`), `BLOSSOM_EVAL_NATIVE_TOOLS=1` (eval, default off),
     `blossom.agent.nativeToolCalls` (extension, default off).
   - **Result.** Edits: zero malformed calls in every native run inspected. Pass rate:
     no gain. Alternating A/B on identical host code — fence 4, 3, 4 (11/15); native
     1, 4, 5 (10/15). Earlier native runs: 3, 2 (before the command fix), 4, 3, 2.
     Failures are now behaviour, not format: re-running failing tests without editing,
     finishing with visible tests green but acceptance failing, shell habits.
   - Host fixes found on the way (both hosts, tests in `test_agent_loop.py`, 45 pass):
     `normalize_command` drops `cd /workspace &&` and `2>&1 || true`;
     `failed_reruns_without_edit` status names the failing file/line after 2 failed test
     runs with no edit; the "you already searched X" status no longer comes back empty
     when no file is in the working set.
   - Conclusion: format is not the bottleneck any more; variance is. Five tasks × one
     run cannot tell a 70% loop from an 80% one — measure with ≥3 cycles before judging
     any change (a cycle takes 5–11 minutes).
2. **Host-run tests** after every edit round — **done in the eval loop 2026-11-20
   (uncommitted)**: `detect_test_command` (`npm test` when package.json has a test
   script, else `python -m pytest -q` when test files exist) and `host_test_entry` in
   `agent_loop.py`; the result is appended to the transcript as a `run_command` with
   `"by": "host"`, and a red host test keeps the turn from ending that round.
   `BLOSSOM_EVAL_HOST_TESTS=0` turns it off. Note the harness's
   `ran_tests_after_last_edit` / `verified_green` now also count host runs. Mirrored in
   the extension 2026-11-21 (uncommitted; see "Fifth part" at the top).
3. **Re-sample a round once** when it has malformed calls — done in the eval loop
   (`RESAMPLE`), not in the extension yet.
4. **Writes as path fences only** — skipped: it breaks on files that contain code fences
   (README), and the rules file is shared with the real router.
5. **Measure with N=3 runs per task** + new tasks — done (8 tasks, `scripts/run_ab.ps1`).
   Mirror `RESAMPLE` and `SHOW_UNREAD` into the extension if they keep paying off.
6. LoRA on the clean trajectories in the run logs — only with the user's approval.

### A/B scripts

**In the repo (use these):** `tools/eval/scripts/run_ab.ps1 -Out <dir> -Var
BLOSSOM_EVAL_HARDEN -Cycles 3 [-Task …] [-Port 8093]` alternates the variable 1/0 over full
cycles (writes `<Out>\on1.log`, `<Out>\runs\on1\<task>\…`; refuses port 8083).
`python tools/eval/scripts/ab_summary.py <Out>` prints the per-task table, per-cycle
scores, mean rounds / failures and host-note counts. An 8-task cycle takes 12–30 minutes.
Do not edit `agent_loop.py`, `host_checks.py`, `harness.py` or the corpus while an A/B
runs: every cycle is a fresh process that reloads them.

Older scratchpad scripts (recreate if the temp folder was cleaned):

`run_cycles.ps1 -Names a,b -Native 0|1` runs full cycles in sequence against the test
router on `:8093`, writing `<name>.log` and `runs\<name>\`. `run_ab.ps1` alternates
fence/native; `run_ab2.ps1` alternates `BLOSSOM_EVAL_HOST_TESTS` 1/0. `fails.py
<transcript.json>…` lists the failed tool calls of a run. A cycle takes 5–11 minutes.
The test router must be restarted after any `ChatRouter.py` change (it does not reload),
and it binds to `CHAT_ROUTER_HOST`, not 127.0.0.1 — check port 8093 is free first.

### Second session (committed in `738417b` / `e016c00`) — every fix is in BOTH `agent_loop.py` and the extension

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
