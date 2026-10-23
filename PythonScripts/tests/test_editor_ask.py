"""The user's ask stays apart from attached files and host blocks."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from EditorContext import extract_user_request, host_ask  # noqa: E402
from PromptTier import PromptTier, detect_prompt_tier  # noqa: E402

PACKED = (
    "The user already has these files open in VS Code.\n"
    "[EDITOR CONTEXT]\n"
    '<<<FILE path="src/app.ts">>>\nconst a = 1;\n<<<END_FILE>>>\n\n'
    "[USER REQUEST]\n"
    "Rename the helper in app.ts\n\n"
    "[PROBLEMS — IDE]\n"
    "Trust these over guessing compile/lint errors for the attached file.\n"
    "src/app.ts:4 error TS2304: Cannot find name 'requests'. npm ERR! 404\n\n"
    "[LINK CHECK]\nNo local href= targets were found.\n\n"
    "[AGENT LOOP]\nRound 1/8. Coding turn (may execute)."
)


def test_host_blocks_after_ask_are_cut():
    assert extract_user_request(PACKED) == "Rename the helper in app.ts"


def test_lowercase_or_inline_brackets_stay_in_ask():
    text = "[USER REQUEST]\nFix [Chapter 2] parsing\n[note] keep the API\nThanks"
    assert extract_user_request(text) == "Fix [Chapter 2] parsing\n[note] keep the API\nThanks"


def test_pinned_ask_wins_for_its_message():
    ask = "Rename the helper in app.ts\n[TODO]\nthen add tests"
    multi = PACKED.replace("Rename the helper in app.ts", ask)
    # Without the host field a bare [TODO] line looks like a host header.
    assert extract_user_request(multi) == "Rename the helper in app.ts"
    with host_ask(ask):
        assert extract_user_request(multi) == ask
        # Other text (e.g. a research query) is not overridden.
        assert extract_user_request("[USER REQUEST]\nwhat is rust") == "what is rust"


def test_ide_errors_stay_out_of_tier_and_ask():
    focus = extract_user_request(PACKED)
    assert "error" not in focus and "404" not in focus
    assert detect_prompt_tier(PACKED) == detect_prompt_tier(
        "[EDITOR CONTEXT]\n<<<FILE path=\"src/app.ts\">>>\nconst a = 1;\n<<<END_FILE>>>\n"
        "[USER REQUEST]\nRename the helper in app.ts"
    )
