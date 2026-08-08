#!/usr/bin/env python3
"""
QLoRA fine-tune on exported Blossom dataset (optional Unsloth stack).

Requires a separate GPU training venv — see requirements-train.txt.
This script is intentionally optional; export_dataset.py works without it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
DEFAULT_DATA = PROJECT_ROOT / "Mind" / "lora_exports" / "alpaca.jsonl"
DEFAULT_OUT = PROJECT_ROOT / "Mind" / "lora_adapters" / "blossom-coder-habits"


def _load_alpaca(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QLoRA train Blossom coder habits (P6)")
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--base-model",
        default="unsloth/Qwen3-Coder-30B-A3B-Instruct-bnb-4bit",
        help="HF model id for Unsloth QLoRA",
    )
    parser.add_argument("--max-steps", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    data_path = Path(args.data)
    if not data_path.is_file():
        print(f"Missing dataset: {data_path}. Run export_dataset.py first.", file=sys.stderr)
        return 1

    rows = _load_alpaca(data_path)
    print(f"Loaded {len(rows)} training row(s) from {data_path}")
    if args.dry_run:
        return 0

    try:
        from unsloth import FastLanguageModel  # type: ignore
        import torch  # type: ignore
        from trl import SFTTrainer  # type: ignore
        from transformers import TrainingArguments  # type: ignore
        from datasets import Dataset  # type: ignore
    except ImportError:
        print(
            "Training deps missing. Create a GPU venv and run:\n"
            "  pip install -r tools/lora/requirements-train.txt\n"
            "See tools/lora/README.md for merge → GGUF steps.",
            file=sys.stderr,
        )
        return 1

    texts = []
    for row in rows:
        texts.append(
            "### Instruction:\n"
            f"{row.get('instruction', '')}\n\n"
            "### Input:\n"
            f"{row.get('input', '')}\n\n"
            "### Response:\n"
            f"{row.get('output', '')}"
        )

    dataset = Dataset.from_dict({"text": texts})
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base_model,
        max_seq_length=4096,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_alpha=16,
        lora_dropout=0.05,
        bias="none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=4096,
        args=TrainingArguments(
            output_dir=str(out_dir),
            per_device_train_batch_size=1,
            gradient_accumulation_steps=4,
            warmup_steps=5,
            max_steps=args.max_steps,
            learning_rate=2e-4,
            logging_steps=5,
            save_steps=max(10, args.max_steps // 2),
            fp16=not torch.cuda.is_bf16_supported(),
            bf16=torch.cuda.is_bf16_supported(),
            optim="adamw_8bit",
        ),
    )
    trainer.train()
    model.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))
    print(f"Adapter saved to {out_dir}")
    print("Next: merge + GGUF export — see tools/lora/README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
