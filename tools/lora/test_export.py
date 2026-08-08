"""Tests for LoRA export (P6)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from blossom_lora.export import (
    TrainingExample,
    export_dataset,
    to_alpaca,
    to_sharegpt,
)


class LoraExportTests(unittest.TestCase):
    def test_sharegpt_and_alpaca_shape(self) -> None:
        ex = TrainingExample(
            user_prompt="Fix foo.ts",
            answer="```typescript path=foo.ts\nconst x = 1;\n```",
            source="test",
            feedback_id="id-1",
        )
        sg = to_sharegpt([ex])
        self.assertEqual(sg[0]["conversations"][0]["from"], "human")
        self.assertIn("path=", sg[0]["conversations"][1]["value"])

        alp = to_alpaca([ex])
        self.assertIn("instruction", alp[0])
        self.assertEqual(alp[0]["input"], "Fix foo.ts")

    def test_export_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = export_dataset(
                output_dir=Path(tmp),
                include_rules_habits=False,
                source_patterns=("local_coder", "blossom_assistant"),
                min_examples=0,
            )
            self.assertTrue(Path(meta["sharegpt"]).is_file())
            self.assertTrue(Path(meta["alpaca"]).is_file())


if __name__ == "__main__":
    unittest.main()
