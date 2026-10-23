"""Pytest bootstrap: tests must never read or write the real Mind/ folder."""

import os
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

_TEST_MIND = tempfile.mkdtemp(prefix="blossom-test-mind-")
os.environ["BLOSSOM_MIND_ROOT"] = _TEST_MIND
os.environ.pop("BLOSSOM_SURFACE", None)
os.environ.pop("BLOSSOM_BRAIN_BROKER_URL", None)
os.environ["COMPACT_ON_STARTUP"] = "false"
os.environ["EVAL_ON_STARTUP"] = "false"
