"""Coder answers must end up as complete, appliable code fences.

Covers the gallery.php failure (empty opener over the labeled one), plan-only replies,
replies cut off mid-file, and ~~~ / ```` fence styles.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ChatRouter  # noqa: E402
from ChatRouter import (  # noqa: E402
    _has_complete_code_fence,
    _has_unclosed_fence,
    _is_file_edit_ask,
    _join_continuation,
    _scan_fences,
)

B = "```"

PACKED = (
    "[EDITOR CONTEXT]\n"
    '<<<FILE path="gallery.php">>>\n<?php echo 1;\n<<<END_FILE>>>\n\n'
    "[USER REQUEST]\n"
    "refactor the php code in here to be more compliant to modern 2026 standard"
)


# --- fence scanning ---------------------------------------------------------


def test_empty_opener_over_labeled_opener_keeps_the_label():
    text = f"{B}php\n{B}html path=gallery.php\n<?php echo 1; ?>\n{B}\n"
    fences, still_open = _scan_fences(text)
    assert fences == [("html path=gallery.php", "<?php echo 1; ?>")]
    assert still_open is None


def test_plan_only_has_no_fence():
    assert not _has_complete_code_fence("Let me refactor the file minimally.")


def test_cut_off_reply_is_unclosed():
    text = f"Here:\n{B}php path=g.php\n<?php\nfunction a() {{\n"
    assert _has_unclosed_fence(text)
    assert not _has_complete_code_fence(text)


def test_tilde_and_four_backtick_fences():
    tilde = "~~~php path=a.php\n<?php echo 'hi';\n~~~\n"
    four = f"````md path=README.md\nUse:\n{B}bash\nnpm test\n{B}\nDone\n````\n"
    assert _scan_fences(tilde)[0] == [("php path=a.php", "<?php echo 'hi';")]
    fences, still_open = _scan_fences(four)
    assert still_open is None
    assert fences[0][0] == "md path=README.md"
    assert f"{B}bash" in fences[0][1]  # inner ``` stays part of the body


def test_closer_glued_to_last_code_line():
    assert _scan_fences(f"{B}js path=b.js\nconsole.log(1);{B}\nok")[0] == [
        ("js path=b.js", "console.log(1);")
    ]


def test_edit_ask_detection():
    ask = "refactor the php code in here to be more compliant to modern 2026 standard"
    assert _is_file_edit_ask(ask, ["gallery.php"])
    assert not _is_file_edit_ask("explain how this works", ["a.php"])
    assert not _is_file_edit_ask(ask, [])


# --- continuation glue ------------------------------------------------------


def test_join_drops_repeated_opener_and_overlap():
    cut = f"{B}php path=g.php\nline1\nline2\n"
    more = f"{B}php path=g.php\nline2\nline3\n{B}\n"
    joined = _join_continuation(cut, more)
    assert joined.startswith(cut)
    assert joined == f"{B}php path=g.php\nline1\nline2\nline3\n{B}\n"


def test_join_mid_line_continuation():
    cut = f"{B}php path=g.php\necho 'he"
    assert _join_continuation(cut, f"llo';\n{B}") == f"{B}php path=g.php\necho 'hello';\n{B}"
    # model re-emits the half line in full
    assert _join_continuation(cut, f"echo 'hello';\n{B}") == f"{B}php path=g.php\necho 'hello';\n{B}"


# --- _local_coder_answer flows (model mocked) -------------------------------


class _FakeStream:
    """Stands in for _stream_local_chat: scripted replies, records calls."""

    def __init__(self, replies: list[tuple[str, str]]):
        self.replies = list(replies)  # (text, finish_reason)
        self.calls: list[dict] = []
        self.streamed: list[str] = []

    def __call__(self, messages, *, on_content=None, meta=None, no_thinking=False, **_):
        text, finish = self.replies.pop(0)
        self.calls.append({"messages": messages, "no_thinking": no_thinking, "live": bool(on_content)})
        if on_content:
            on_content(text)
        if meta is not None:
            meta["raw"] = text
            meta["finish_reason"] = finish
        return text.strip()


def _run(replies):
    fake = _FakeStream(replies)
    client_text: list[str] = []
    with (
        patch.object(ChatRouter, "_stream_local_chat", fake),
        patch.object(ChatRouter, "query_memories", return_value=[]),
    ):
        answer = ChatRouter._local_coder_answer(PACKED, on_content=client_text.append)
    return answer, fake, "".join(client_text)


def test_plan_only_gets_one_no_thinking_push():
    code = f"{B}php path=gallery.php\n<?php declare(strict_types=1);\n{B}\n"
    answer, fake, client = _run([("Let me refactor the file.", "stop"), (code, "stop")])
    assert len(fake.calls) == 2
    assert fake.calls[1]["no_thinking"] is True
    assert _has_complete_code_fence(answer)
    assert client.strip() == answer


def test_cut_off_reply_is_continued_and_client_gets_the_same_text():
    first = f"{B}php path=gallery.php\n<?php\nfunction a(): int {{\n"
    rest = f"{B}php path=gallery.php\nfunction a(): int {{\n    return 1;\n}}\n{B}\n"
    answer, fake, client = _run([(first, "length"), (rest, "stop")])
    assert len(fake.calls) == 2
    assert fake.calls[1]["live"] is False  # glued server-side, then streamed as a tail
    assert answer == (
        f"{B}php path=gallery.php\n<?php\nfunction a(): int {{\n    return 1;\n}}\n{B}"
    )
    assert client.strip() == answer
    assert not _has_unclosed_fence(answer)


def test_complete_answer_runs_once_with_output_contract():
    code = f"{B}php path=gallery.php\n<?php declare(strict_types=1);\n{B}\n"
    _, fake, _ = _run([(code, "stop")])
    assert len(fake.calls) == 1
    system_text = "\n".join(
        m["content"] for m in fake.calls[0]["messages"] if m["role"] == "system"
    )
    assert "[OUTPUT CONTRACT" in system_text
