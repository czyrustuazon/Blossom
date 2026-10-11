# Blossom Agent Execution Layer

Sandboxed Python REPL with pre-baked `agent_utils` for Git, Excel, PDF, and data/math tasks. Designed to reduce token usage via short helper calls instead of raw boilerplate.

## Quick start (local — recommended)

```powershell
cd Documents\Blossom
.\start-server.ps1
```

When `AGENT_EXECUTION_ENABLED=true` (default in `.env.example`), `start-server.ps1` installs `agent_execution` deps and starts the sandbox on `:8082` alongside ChatRouter.

One-time manual start:

```powershell
cd Documents\Blossom\agent_execution
pip install -e .
python AgentExecutor.py
curl http://127.0.0.1:8082/health
```

## Docker (optional)

```powershell
cd Documents\Blossom\agent_execution
docker compose up --build -d
```

## Local dev (no Docker)

Same as one-time manual start above.

## API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Liveness |
| `/v1/prompt` | GET | Agent system prompt |
| `/v1/execute` | POST | Run Python code (`{"code": "..."}`) |

Generated files should be written under `./workspace/` (mounted at `agent_execution/workspace/`).

## ChatRouter routing

`AgentRouter.py` exposes `is_agent_execution_request()` and `classify_route()`. ChatRouter imports these when `AGENT_EXECUTION_ENABLED=true` (default) and routes REPL-style tasks to the sandbox before the IDE coding path.

Environment:

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_EXECUTION_ENABLED` | `true` | Enable agent route in ChatRouter |
| `AGENT_EXECUTOR_URL` | `http://127.0.0.1:8082` | Sandbox base URL |
| `AGENT_EXEC_TIMEOUT` | `30` | Max seconds per execute call |

## Pre-baked utilities

```python
import agent_utils as au

au.git_get_staged_diff()
au.git_status_short()
au.git_auto_commit_and_push("feat: add report")
au.read_csv_summary("data.csv")
au.create_styled_excel(df, "./workspace/report.xlsx")
au.save_figure(fig, "./workspace/plot.png")
au.read_json("config.json")
au.write_json("./workspace/out.json", {"ok": True})
au.extract_pdf_text("doc.pdf")
au.merge_pdfs(["a.pdf", "b.pdf"], "./workspace/merged.pdf")
```

See `prompts/agent_system_prompt.md` for the full agent mandate.
