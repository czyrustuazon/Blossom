# Brains setup

`models/` and `runtime/` are **gitignored** (tens of GB). Clone the repo, then populate this folder before local chat/coding will work.

Cloud-only mode is possible if you set Claude/Gemini keys and skip local GGUFs, but the default design expects both pieces below.

---

## Expected layout

```
Brains/
  runtime/
    llama-server.exe          # required
    *.dll                     # CUDA / VC runtime deps shipped with the build
  models/
    conversational/
      Qwen3-8B-Q4_K_M.gguf    # default persona / voice model
    coding/
      Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf   # default local coder
```

Defaults come from `PythonScripts/MemoryUpdater.py` and `LlamaServerManager.py`. Override paths in `PythonScripts/.env`:

```env
PERSONA_MODEL_PATH=C:\path\to\your-persona.gguf
CODER_MODEL_PATH=C:\path\to\your-coder.gguf
LOCAL_VOICE_MODEL=Qwen3-8B-Q4_K_M.gguf
LOCAL_CODER_MODEL=Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf
```

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

1. Create `Brains/models/conversational/`
2. Download a Q4_K_M (or similar) GGUF for your chat model — default name:
   - `Qwen3-8B-Q4_K_M.gguf`
3. Place it at:
   - `Brains/models/conversational/Qwen3-8B-Q4_K_M.gguf`

Hugging Face search tip: look for repos with **GGUF** in the name (e.g. community Quants of Qwen3-8B).

### Coder (optional but recommended)

1. Create `Brains/models/coding/`
2. Download the coding GGUF — default name:
   - `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf`
3. Place it at:
   - `Brains/models/coding/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf`

If the coder file is missing, ChatRouter skips the local coder and falls through to Claude/Gemini (when keys are set).

**VRAM note:** persona (~8B) and coder (~30B) are **hot-swapped** — only one loads at a time. A single high-VRAM GPU is assumed.

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

Then open `http://127.0.0.1:8081/health`. You should see `coder_available` true/false depending on whether the coding GGUF is present.

Point clients (including Blossom Assistant) at:

`http://127.0.0.1:8081/v1/chat/completions`

---

## Common failures

| Symptom | Likely cause |
|---------|----------------|
| `llama-server.exe not found` | Runtime not extracted into `Brains/runtime/` |
| Exit code `-1073741515` / missing DLL | Incomplete runtime folder; restore DLLs next to the exe |
| Wrong GPU / CPU-only | Need CUDA 12 Windows build, not Vulkan/CPU-only or CUDA 13 mismatch |
| Coder always “cloud” | Coding GGUF missing or `CODER_MODEL_PATH` wrong |
| Out of memory / slow load | Ctx size / GPU layers in `.env` (`PERSONA_CTX_SIZE`, `CODER_CTX_SIZE`, `LLAMA_N_GPU_LAYERS`) |

---

## What is *not* in git

- `Brains/models/**` (GGUFs)
- `Brains/runtime/**` (binaries + DLLs)
- `Mind/chromadb/`, `Mind/*.db` (personal memory)

This `README.md` is tracked so clone → read → download is enough to rebuild `Brains/`.
