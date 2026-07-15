# Brains setup

`models/` and `runtime/` are **gitignored** (tens of GB). Clone the repo, then populate this folder before local chat/coding will work.

Cloud-only mode is possible if you set Claude/Gemini keys and skip local GGUFs, but the default design expects both pieces below.

---

## Expected layout

```
Brains/
  add-model.ps1                 # download any GGUF into models/
  model-presets.json            # known HF repos (DeepSeek, etc.)
  runtime/
    llama-server.exe            # required
    *.dll                       # CUDA / VC runtime deps shipped with the build
  models/
    conversational/
      Qwen3-8B-Q4_K_M.gguf      # default persona / voice model
    coding/
      Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf   # default primary coder
      DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf  # optional second coder
```

Paths in `PythonScripts/.env` can be **absolute** or **relative to `Brains/models/`**:

```env
PERSONA_MODEL_PATH=conversational/Qwen3-8B-Q4_K_M.gguf
CODER_MODEL_PATH=coding/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf

# Agnostic multi-coder ladder (tried in order before cloud when uncertain):
CODER_MODELS=coding/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf,coding/DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf

# Or just primary + one alt (same idea):
# CODER_ALT_MODEL_PATH=coding/DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf
```

`CODER_MODELS` wins when set. Otherwise Blossom uses `CODER_MODEL_PATH` then optional `CODER_ALT_MODEL_PATH`.

---

## Add any local LLM (recommended)

From this folder (or repo root):

```powershell
# List known presets
.\add-model.ps1 -ListPresets

# Download DeepSeek as second coder (~10GB)
.\add-model.ps1 -Preset deepseek-coder-v2-lite

# Or any GGUF of your choice
.\add-model.ps1 -Role coding -Repo "bartowski/SomeModel-GGUF" -File "SomeModel-Q4_K_M.gguf"
.\add-model.ps1 -Role conversational -Repo "owner/Chat-GGUF" -File "Chat-Q4_K_M.gguf"
```

The script prints the `.env` line to add. Then restart `start-server.ps1`.

Requires `pip install huggingface_hub` (also listed in `PythonScripts/requirements.txt`).

---

## 1. Runtime (`Brains/runtime/`)

You need a **Windows x64 llama.cpp** build with **CUDA 12** (for NVIDIA GPUs like RTX 4090).

1. Download a release from [ggerganov/llama.cpp](https://github.com/ggerganov/llama.cpp/releases) (or a trusted CUDA 12 Windows build).
2. Extract so that `llama-server.exe` sits directly in `Brains/runtime/` (not nested in a random subfolder).
3. Keep the CUDA / runtime DLLs that ship next to the exe in the same folder. Do **not** delete obscure DLLs “to save space” — some (e.g. multimodal helpers) are still linked and removing them can crash the process.

Check:

```powershell
Test-Path ".\Brains\runtime\llama-server.exe"
```

---

## 2. Models (`Brains/models/`)

You need **GGUF** files (not raw Hugging Face safetensors).

### Persona (required for local casual chat)

1. Create `Brains/models/conversational/` (or use `add-model.ps1 -Role conversational …`)
2. Download a Q4_K_M (or similar) GGUF — default name:
   - `Qwen3-8B-Q4_K_M.gguf`
3. Place it at:
   - `Brains/models/conversational/Qwen3-8B-Q4_K_M.gguf`

Hugging Face search tip: look for repos with **GGUF** in the name (e.g. community Quants of Qwen3-8B).

### Coders (optional but recommended)

Primary defaults to:

- `Brains/models/coding/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf`

Add DeepSeek (or anything else) with `add-model.ps1`, then set `CODER_MODELS` / `CODER_ALT_MODEL_PATH`.

When coding is uncertain (weak answer, `ESCALATE_CLOUD`, incomplete multi-file heuristics), Blossom tries the **next local coder** before Claude/Gemini.

If no coding GGUF is present, ChatRouter skips local coders and falls through to cloud (when keys are set).

**VRAM note:** persona and coder GGUFs are **hot-swapped** — only one loads at a time. Switching to an alt coder reloads llama-server (seconds). A single high-VRAM GPU is assumed.

---

## 3. Env + Python

```powershell
cd PythonScripts
copy .env.example .env
# edit .env — at least cloud keys if you want fallback; model paths if non-default

pip install -r requirements.txt
```

---

## 4. Start

From the repo root:

```powershell
& ".\start-server.ps1"
```

Then open `http://127.0.0.1:8081/health`. Check:

- `coder_available`
- `coder_ladder` / `coder_ladder_available`

Point clients (including Blossom Assistant) at:

`http://127.0.0.1:8081/v1/chat/completions`

---

## Common failures

| Symptom | Likely cause |
|---------|----------------|
| `llama-server.exe not found` | Runtime not extracted into `Brains/runtime/` |
| Exit code `-1073741515` / missing DLL | Incomplete runtime folder; restore DLLs next to the exe |
| Wrong GPU / CPU-only | Need CUDA 12 Windows build, not Vulkan/CPU-only or CUDA 13 mismatch |
| Coder always “cloud” | Coding GGUF missing or `CODER_MODEL_PATH` / `CODER_MODELS` wrong |
| Alt coder never tried | File missing, or not listed in `CODER_MODELS` / `CODER_ALT_MODEL_PATH` |
| Out of memory / slow load | Ctx size / GPU layers in `.env` (`PERSONA_CTX_SIZE`, `CODER_CTX_SIZE`, `LLAMA_N_GPU_LAYERS`) |

---

## What is *not* in git

- `Brains/models/**` (GGUFs)
- `Brains/runtime/**` (binaries + DLLs)
- `Mind/chromadb/`, `Mind/*.db` (personal memory)

This `README.md`, `add-model.ps1`, and `model-presets.json` are tracked so clone → download → env is enough to rebuild `Brains/`.
