# Blossom

Local-first personal companion: llama.cpp GGUFs + FastAPI ChatRouter (`:8081`) + SQLite + Chroma, with optional Claude/Gemini, web search, and spoken replies.

## Quick start

1. Populate **`Brains/`** (GGUFs + `llama-server` runtime) — see **[Brains/README.md](./Brains/README.md)**.
2. Copy `PythonScripts/.env.example` → `PythonScripts/.env` and fill keys / paths.
3. `pip install -r PythonScripts/requirements.txt`
4. Start:

```powershell
& ".\start-server.ps1"
```

Point clients at `http://127.0.0.1:8081/v1/chat/completions`.

## Clients

| Client | Role |
|--------|------|
| **Blossom Companion** (`Documents\Blossom Companion`) | Chat UI: personas, JA/EN locale, spoken replies |
| **Blossom Assistant** (`Documents\Blossom Assistant`) | VS Code extension: Apply, deletes, editor context |

## Optional: spoken replies (Voice)

See **[`Voice/README.md`](./Voice/README.md)**.

1. Drop RVC packs under `Voice/characters/<Name>/{Jpn,Eng}/` (`.pth` + `.index`).
2. Set `VOICE_ENABLED=true` (and usually `VOICE_PYTHON` to a CUDA venv).
3. In Companion → Personality, pick **Voice pack** (`voice_id`).
4. `start-server.ps1` launches the Voice service on `:8090`.

| Locale | Pipeline |
|--------|----------|
| Japanese | Style-Bert-VITS2 → character RVC |
| English | Edge TTS → character RVC |

Emotion is classified per reply; audio streams as `blossom_audio` after text. Packs are auto-discovered — no path edits in `presets.yaml` per character.

## Where we’re at

See **[PROGRESS.md](./PROGRESS.md)** for architecture, what’s built, roadblocks, and lessons learned.
