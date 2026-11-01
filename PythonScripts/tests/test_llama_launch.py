"""Launch-window helpers: trained-context cap and mmap decision."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import LlamaServerManager as lsm  # noqa: E402

PROJECT = SCRIPT_DIR.parent
MODELS = PROJECT / "Brains" / "models"


class ContextCapTests(unittest.TestCase):
    def test_known_ggufs(self):
        cases = {
            MODELS / "coding" / "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf": 262144,
            MODELS / "coding" / "DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf": 163840,
            MODELS / "conversational" / "Qwen_Qwen3-14B-Q4_K_M.gguf": 32768,
        }
        for path, trained in cases.items():
            if not path.is_file():
                self.skipTest(f"missing {path.name}")
            self.assertEqual(lsm.gguf_context_length(path), trained, path.name)

    def test_cap_stops_at_trained_length(self):
        coder = MODELS / "coding" / "DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf"
        if not coder.is_file():
            self.skipTest("deepseek gguf missing")
        self.assertEqual(lsm.cap_ctx_to_trained(262144, coder), 163840)
        self.assertEqual(lsm.cap_ctx_to_trained(65536, coder), 65536)

    def test_missing_file_leaves_ctx_alone(self):
        missing = MODELS / "coding" / "does-not-exist.gguf"
        self.assertIsNone(lsm.gguf_context_length(missing))
        self.assertEqual(lsm.cap_ctx_to_trained(262144, missing), 262144)


class MmapDecisionTests(unittest.TestCase):
    def test_gpu_only_profile_keeps_mmap(self):
        path = MODELS / "coding" / "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"
        self.assertFalse(lsm.should_disable_mmap(path, 0, 64_000))

    def test_cpu_experts_need_room_for_the_file(self):
        path = MODELS / "coding" / "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"
        if not path.is_file():
            self.skipTest("coder gguf missing")
        file_mib = path.stat().st_size // (1024 * 1024)
        self.assertFalse(
            lsm.should_disable_mmap(path, 12, file_mib + lsm.MMAP_DISABLE_MARGIN_MIB - 1)
        )
        self.assertTrue(
            lsm.should_disable_mmap(path, 12, file_mib + lsm.MMAP_DISABLE_MARGIN_MIB)
        )

    def test_unknown_free_ram_keeps_mmap(self):
        path = MODELS / "coding" / "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"
        self.assertFalse(lsm.should_disable_mmap(path, 12, None))


if __name__ == "__main__":
    unittest.main()
