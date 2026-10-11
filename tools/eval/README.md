# Blossom eval harness (P4)

Measure whether Blossom coding changes **actually help** — corpus-agnostic, not PHP-only.

The first bundled corpus is **PHP modernization** because `MustDo.md` references `blossom-php-modernization-training-set`. The same harness runs **C#**, **reverse-engineering / assembly** (response-only scoring), or any domain you define.

## Quick start

From repo root (ChatRouter running on `:8081`):

```powershell
pip install -r tools/eval/requirements.txt
python tools/eval/run_eval.py list
python tools/eval/run_eval.py run --corpus php-modernization --dry-run
python tools/eval/run_eval.py run --corpus php-modernization
python tools/eval/run_eval.py report --corpus php-modernization
```

## Corpora layout

```
corpora/my-corpus/
  corpus.json          # id, title, domains[]
  tasks/my-task/
    task.json          # prompt, fixtures, checks, mode
    fixtures/...       # starting files (apply mode)
```

### Task modes

| mode | Use for |
|------|---------|
| `apply` (default) | Code tasks — model returns `path=` fences; harness writes files and checks disk |
| `analyze_only` | Assembly / Ghidra / prose analysis — scores **response text** only (`response_contains`, `response_regex`) |

### Check types

| type | Applies to |
|------|------------|
| `contains` / `not_contains` | File under work dir |
| `regex` | File content |
| `command` | Shell in work dir (`php -l`, `dotnet build`, custom scripts) |
| `response_contains` / `response_regex` | Model answer (RE, assembly write-ups) |
| `manual` | Placeholder for human review |

## Adding C#, assembly, NLPP, etc.

1. Copy `corpora/example-csharp` or `corpora/example-reverse-engineering` as a template.
2. Set `"domain"` and `"domains"` in `corpus.json`.
3. For **C# / compiled languages**: add fixtures + optional `dotnet build` / `msbuild` command checks.
4. For **assembly / Ghidra**: use `mode: analyze_only` and `response_regex` (hex addresses, xref vocabulary) until you wire a Ghidra CLI scorer.
5. Point at an external corpus: `run --corpus D:\corpora\blossom-php-modernization-training-set` if it follows the same layout.

## Results

SQLite: `Mind/eval_results.db` — pass/fail per run, check breakdown, timestamps. Track pass rate over time with `run_eval.py report`.

## Environment

| Variable | Default |
|----------|---------|
| `CHAT_ROUTER_HOST` | `127.0.0.1` |
| `CHAT_ROUTER_PORT` | `8081` |
| `BLOSSOM_EVAL_CHAT_URL` | full URL override |
| `BLOSSOM_EVAL_MODEL` | `local-coder` |
| `EVAL_ON_STARTUP` | `true` — run list/dry-run/live/report when ChatRouter boots |
| `EVAL_ON_STARTUP_DRY_RUN_ONLY` | `false` — set `true` to skip live LLM eval on boot |
| `EVAL_CORPUS` | `php-modernization` |

### Startup integration

When you run `start-server.ps1`:

1. `pip install -r tools/eval/requirements.txt` (if `EVAL_ON_STARTUP` is not false)
2. After ChatRouter listens, background task runs: `list` → `dry-run` → `run` → `report`

Logs appear as `[Blossom Eval]` in the ChatRouter console. Disable with `EVAL_ON_STARTUP=false` in `PythonScripts/.env`.

### Boot noise: dry-run FAIL (usually ignore)

On startup you may see something like:

```text
[Blossom Eval] run --corpus php-modernization --dry-run
[Blossom Eval] Finished 1 task(s): 0 passed, 1 failed
[Blossom Eval] FAIL login-mysql
  [x] no_mysql / uses_pdo / …
  [x] php_syntax: 'php' is not recognized …
[Blossom Eval] dry-run failed — skipping live eval
```

**Why it shows up**

- Startup always runs a **dry-run** first. Dry-run does **not** call the coder; fixtures stay as the old broken code.
- Checks still expect a modernized file (`PDO`, `password_hash`, no `mysql_`) → **expected FAIL**.
- If `php` is not on PATH, the `php -l` syntax check fails too (environment, not Blossom chat).
- A non-zero dry-run currently **skips the live LLM eval** on boot — so this is not evidence the coder is bad; the model never ran.

**When it actually matters**

- You are measuring coding quality / PHP modernization pass rate.
- Then: put `php` on PATH if you want syntax checks, and run a **live** eval with ChatRouter up:

```powershell
python tools/eval/run_eval.py run --corpus php-modernization
python tools/eval/run_eval.py report --corpus php-modernization
```

**When to ignore**

- Daily companion / casual chat / Voice — ChatRouter is fine; this is harness telemetry only.
- To silence boot eval entirely: `EVAL_ON_STARTUP=false` in `PythonScripts/.env`.

## Not LoRA training data

Eval corpora measure **pass rate**. Failed runs inform `coding_lessons` / rule updates (Phase A). LoRA (Phase C) is separate.
