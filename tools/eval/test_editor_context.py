"""
ChatRouter's editor-context packing must never drop the agent loop.

Real-extension eval 2026-11-21: every Blossom Assistant agent round with attached files was
rebuilt as request + files only, so the tool transcript, working set and host status vanished;
the coder re-read the attached files every round and never edited.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "PythonScripts"))

from EditorContext import pack_editor_context  # noqa: E402

FILES = (
    "[EDITOR CONTEXT]\n"
    "<<<FILE path=\"ledger/models.py\">>>\n"
    + "def make_entry(d, a):\n    return {'d': d, 'a': a}\n" * 40
    + "<<<END_FILE>>>\n"
)
AGENT_ROUND = (
    "[USER REQUEST]\nReplace make_entry with a dataclass.\n\n"
    + FILES
    + "\n[AGENT TOOL TRANSCRIPT — compact]\n### Round 1 — read_file (ok)\nResult:\n// ledger/book.py\n...\n"
    "\n[CONTINUE — agent round]\nRound 2/11.\n"
    "\n[RESEARCH STATUS — from the host]\nAlready read: ledger/book.py. EXECUTE now.\n"
)


def test_agent_round_within_budget_is_untouched():
    out, stats = pack_editor_context(AGENT_ROUND, token_budget=40_000)
    assert out == AGENT_ROUND
    assert stats["mode"] == "agent-round"


def test_agent_round_over_budget_keeps_every_section():
    out, stats = pack_editor_context(AGENT_ROUND, token_budget=300)
    for section in ("[USER REQUEST]", "[AGENT TOOL TRANSCRIPT", "[CONTINUE — agent round]",
                    "[RESEARCH STATUS", "EXECUTE now"):
        assert section in out, section
    assert stats["packed"] is True
    assert out.index("[USER REQUEST]") < out.index("<<<FILE") < out.index("[AGENT TOOL TRANSCRIPT")


def test_one_shot_prompt_still_packs():
    plain = "[USER REQUEST]\nfix the bug\n\n" + FILES
    out, stats = pack_editor_context(plain, token_budget=40_000)
    assert stats["packed"] is True
    assert "[PACKED EDITOR CONTEXT]" in out
