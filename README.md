# Blossom

Local-first personal companion: llama.cpp GGUFs + FastAPI ChatRouter (`:8081`) + SQLite + Chroma, with optional Claude/Gemini and web search.

## Quick start

1. Populate **`Brains/`** (GGUFs + `llama-server` runtime) — see **[Brains/README.md](./Brains/README.md)**.
2. Copy `PythonScripts/.env.example` → `PythonScripts/.env` and fill keys / paths.
3. `pip install -r PythonScripts/requirements.txt`
4. Start:

```powershell
& ".\start-server.ps1"
```

Point clients at `http://127.0.0.1:8081/v1/chat/completions`.

## Where we’re at

See **[PROGRESS.md](./PROGRESS.md)** for architecture, what’s built, roadblocks, and lessons learned.

The VS Code client is a separate project: `Documents\Blossom Assistant`.
