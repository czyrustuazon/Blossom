# Blossom Voice

GPU FastAPI service for spoken companion replies. Character RVC packs live under **`Voice/characters/`** (separate from service code for a clean gitignore). Personas pick a pack via `voice_id`.

## Pipelines

| Locale | Flow |
|--------|------|
| `ja` | Style-Bert-VITS2 (emotion style) → character RVC (`…/Jpn/`) |
| `en` | Edge TTS (US neural + emotion rate/pitch) → character RVC (`…/Eng/`) |

Emotion labels (`angry`, `happy`, `sad`, `surprise`, `fear`, `disgust`, `neutral`) map to SBV2 style / Edge prosody **and** RVC pitch in presets. `neutral` is speakable (calm mid register); unmatched heuristics default to it.

## Layout

```text
Voice/
  pipeline.py, service.py, voices.py, presets.yaml, …
  model_assets/          # SBV2 download cache (gitignored)
  characters/            # RVC packs only (gitignored except README)
    VOICE_1/
      Jpn/               # *.pth + *.index
      Eng/
    VOICE_2/
      Jpn/
      Eng/
```

API: `GET /v1/voices` lists packs. `POST /v1/speak` accepts optional `voice_id`.

## One-time setup

**Recommended:** dedicated venv (keeps CUDA stack away from ChatRouter):

```powershell
cd C:\Users\Zepse\Documents\Blossom\Voice
.\setup-venv.ps1
```

`style-bert-vits2` pins `omegaconf==2.0.6`, which **pip ≥ 24.1 rejects** — the setup script uses `pip<24.1` for that step.

Or set an existing interpreter in `PythonScripts/.env`:

```env
VOICE_PYTHON=C:\path\to\python.exe
```

SBV2 assets download into `model_assets/` on first Japanese synth.

## Start

With `VOICE_ENABLED=true`, Blossom’s `start-server.ps1` launches this service.

Manual:

```powershell
cd C:\Users\Zepse\Documents\Blossom\Voice
python -m uvicorn service:app --host 127.0.0.1 --port 8090
```

## Tracked vs local

| Path | Tracked? |
|------|----------|
| `*.py`, `presets.yaml`, `requirements.txt`, `setup-venv.ps1`, `characters/README.md` | yes |
| `characters/<Name>/…`, `model_assets/`, `.venv/`, `*.pth`, `*.index` | no |

## Presets

Edit [`presets.yaml`](presets.yaml) for:

- `default_voice` — folder under `characters/` when `voice_id` is omitted
- shared RVC knobs (`index_rate`, `protect`, `f0method`, …)
- per-emotion SBV2 style / Edge rate / RVC pitch
- Edge voice name (`english.voice`)

## Env vars

| Variable | Default | Meaning |
|----------|---------|---------|
| `VOICE_HOST` / `VOICE_PORT` | `127.0.0.1` / `8090` | Bind |
| `VOICE_PRELOAD` | `true` | Load SBV2 + default RVC at startup |
| `VOICE_MAX_CHARS` | `220` | Truncate speech text |
| `VOICE_SPLIT_SENTENCES` | `false` | Multi-pass synth (slower) |
| `VOICE_PYTHON` | (PATH `python`) | Interpreter for `start-server.ps1` |
| `VOICE_DIR` | `<Blossom>/Voice` | Service root |
| `VOICE_CHARACTERS_DIR` | `<Voice>/characters` | Pack discovery root |

## ChatRouter

```env
VOICE_ENABLED=true
VOICE_SERVICE_URL=http://127.0.0.1:8090
```

`GET /v1/voices` is proxied for Companion. Active persona `voice_id` is sent on speak.
