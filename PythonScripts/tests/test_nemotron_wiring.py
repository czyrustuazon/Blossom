"""Lightning coder profiles and the Bolt persona brain stay on the right GGUF."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import LlamaServerManager as lsm  # noqa: E402
import LocalModels  # noqa: E402
from MemoryUpdater import _normalize_profile  # noqa: E402

LIGHTNING = Path("NVIDIA-Nemotron-3.5-Lightning-30B-A3B-IQ4_XS.gguf")
QWEN = Path("Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf")
RULES = "Nemotron-3.5-Lightning=65536:q8_0:0:0|262144:q8_0:0:0"
QWEN_PROFILES = [
    lsm.CoderProfile(65536, "q8_0", 0, 21400),
    lsm.CoderProfile(262144, "q4_0", 12, 21300),
]


class CoderProfileTests(unittest.TestCase):
    def test_lightning_does_not_inherit_qwen_cpu_experts(self):
        profiles = lsm.profiles_for_model(LIGHTNING, RULES, QWEN_PROFILES)
        self.assertEqual([p.ctx for p in profiles], [65536, 262144])
        self.assertTrue(all(p.n_cpu_moe == 0 for p in profiles))
        self.assertTrue(all(p.vram_mib == 0 for p in profiles))

    def test_qwen_keeps_the_measured_fallback(self):
        profiles = lsm.profiles_for_model(QWEN, RULES, QWEN_PROFILES)
        self.assertEqual(profiles[1].n_cpu_moe, 12)
        self.assertEqual(profiles[1].cache_type, "q4_0")

    def test_long_prompt_picks_the_larger_lightning_window(self):
        profiles = lsm.profiles_for_model(LIGHTNING, RULES, QWEN_PROFILES)
        chosen = next(p for p in profiles if p.ctx >= 200_000)
        self.assertEqual(chosen.ctx, 262144)
        self.assertEqual(chosen.n_cpu_moe, 0)


class PersonaBrainTests(unittest.TestCase):
    def test_bolt_brain_resolves_to_the_alt_gguf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "qwen.gguf"
            bolt = root / "Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf"
            main.write_bytes(b"q")
            bolt.write_bytes(b"b")
            saved = {
                key: os.environ.get(key)
                for key in ("PERSONA_MODEL_PATH", "PERSONA_ALT_MODEL_PATH")
            }
            os.environ["PERSONA_MODEL_PATH"] = str(main)
            os.environ["PERSONA_ALT_MODEL_PATH"] = str(bolt)
            try:
                self.assertEqual(LocalModels.persona_brain_path(""), main.resolve())
                self.assertEqual(LocalModels.persona_brain_path("bolt"), bolt.resolve())
                self.assertEqual(LocalModels.persona_brain_path("nope"), main.resolve())
                ids = [b["id"] for b in LocalModels.persona_brain_catalog()]
                self.assertEqual(ids, ["", "bolt"])
            finally:
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_missing_bolt_file_falls_back_to_qwen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "qwen.gguf"
            main.write_bytes(b"q")
            saved = {
                key: os.environ.get(key)
                for key in ("PERSONA_MODEL_PATH", "PERSONA_ALT_MODEL_PATH")
            }
            os.environ["PERSONA_MODEL_PATH"] = str(main)
            os.environ["PERSONA_ALT_MODEL_PATH"] = str(root / "missing-bolt.gguf")
            try:
                self.assertEqual(LocalModels.persona_brain_path("bolt"), main.resolve())
            finally:
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_profile_brain_only_accepts_bolt(self):
        self.assertEqual(_normalize_profile({"brain": "bolt"})["brain"], "bolt")
        self.assertEqual(_normalize_profile({"brain": "lightning"})["brain"], "")
        self.assertEqual(_normalize_profile({})["brain"], "")


if __name__ == "__main__":
    unittest.main()
