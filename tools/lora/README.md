# Blossom LoRA pipeline (P6)

Train **frozen output habits** only (path= fences, CREATE vs EDIT, Summary card) — **not** project facts or Chroma lessons.

RAG (👍/👎 → `coding_lessons`) remains the primary learning path. LoRA is optional Phase C after eval + RAG plateau.

## Pipeline

```
👍 feedback_turns (SQLite)  ─┐
coding_rules.txt (habits)    ─┼─► export_dataset.py → Mind/lora_exports/*.jsonl
                              │
                              ▼
                    train_qlora.py (GPU venv + Unsloth)
                              │
                              ▼
                    Mind/lora_adapters/blossom-coder-habits/
                              │
                              ▼
              merge + GGUF export (llama.cpp / Unsloth docs)
                              │
                              ▼
              Brains/models/coding/<name>-lora.gguf
              update CODER_MODELS in .env → A/B vs baseline
```

## 1. Export dataset

```powershell
python tools/lora/export_dataset.py
```

Writes:

| File | Format |
|------|--------|
| `Mind/lora_exports/sharegpt.jsonl` | ShareGPT conversations |
| `Mind/lora_exports/alpaca.jsonl` | Alpaca instruction/input/output |
| `Mind/lora_exports/export_meta.json` | Counts + paths |

Sources (default): thumbs-**up** on coding route where `source` matches `blossom_assistant_*`, `cursor_manual`, `local_coder`. Optionally merges synthetic habit chunks from `PythonScripts/coding_rules.txt`.

```powershell
# Stricter: only cloud escalation thumbs-up
python tools/lora/export_dataset.py --source blossom_assistant_cursor --source blossom_assistant_gemini

# Feedback only (no coding_rules synthetic rows)
python tools/lora/export_dataset.py --no-rules-habits
```

## 2. QLoRA train (optional GPU venv)

```powershell
python -m venv .venv-lora
.\.venv-lora\Scripts\Activate.ps1
pip install -r tools/lora/requirements-train.txt
python tools/lora/train_qlora.py --dry-run
python tools/lora/train_qlora.py --max-steps 60
```

Default base: `unsloth/Qwen3-Coder-30B-A3B-Instruct-bnb-4bit` (matches primary coder family).

## 3. Merge adapter → GGUF

Follow [Unsloth GGUF export](https://docs.unsloth.ai/basics/running-and-saving-models) or llama.cpp `export-lora` for your build. Typical flow:

1. Merge LoRA into base weights (Unsloth `save_pretrained_merged` or equivalent).
2. Convert merged weights to GGUF (Q4_K_M recommended for 4090).
3. Copy into `Brains/models/coding/`.
4. Add to ladder **after** baseline for A/B:

```env
CODER_MODELS=coding/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf,coding/Qwen3-Coder-30B-A3B-habits-lora-Q4_K_M.gguf
```

5. Compare pass rate: `python tools/eval/run_eval.py report`

## What NOT to LoRA

- One-off NLPP facts (use P5 seed + RAG)
- Cursor/Gemini prose without fences
- Companionship / persona voice (separate track if ever needed)

## Environment

| Variable | Purpose |
|----------|---------|
| `LORA_EXPORT_DIR` | Override export output (future) |
| `LORA_MIN_EXAMPLES` | Minimum rows before train (default 1 for export; raise for real runs) |

Recommend **≥20** diverse 👍 coding examples before a serious LoRA run.

**Desktop workflow guide:** `Documents\Project Organizer\blossom-coding-workflow\` — launch from **Project Organizer → Blossom Coding Workflow**.
