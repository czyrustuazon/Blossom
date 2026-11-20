"""Regression tests for the headless Blossom Assistant agent loop (blossom_eval.agent_loop).

The malformed tool calls below are verbatim from Blossom's own replies during the
project-refactor training cycles.
"""

from __future__ import annotations

from pathlib import Path

from blossom_eval.agent_loop import (
    TranscriptEntry,
    Workspace,
    build_research_status,
    format_transcript,
    parse_tool_calls,
    repair_json_escapes,
    working_set_indices,
)

FENCE = "`" * 3

# cycle 2, cjs-to-esm round 6: backtick escaped as \` inside a JSON string.
BACKTICK_CALL = (
    r'{"name":"write_file","arguments":{"path":"src/lib/format.js","content":"const PRIORITY_MARK'
    r' = { high: \"!!\", normal: \"\", low: \"~\" };\n\nexport function formatTask(task) {\n  const box'
    r' = task.done ? \"[x]\" : \"[ ]\";\n  const mark = PRIORITY_MARK[task.priority] || \"\";\n  return'
    r' \`${box} ${mark}${task.title}\`.replace(/\\s+$/, \"\");\n}\n\nexport { PRIORITY_MARK };\n"}}'
)
# cycle 1, cjs-to-esm round 1: regex alternation in a literal search.
REGEX_ESCAPE_CALL = r'{"name":"search_text","arguments":{"query":"require\|module\.exports"}}'


def _fence(body: str) -> str:
    return f"{FENCE}tool_call\n{body}\n{FENCE}"


def test_backtick_escape_repaired_to_valid_js():
    calls = parse_tool_calls(_fence(BACKTICK_CALL))
    assert [c["name"] for c in calls] == ["write_file"]
    content = calls[0]["arguments"]["content"]
    assert "return `${box} ${mark}${task.title}`.replace(/\\s+$/, \"\");" in content
    assert "\\`" not in content  # no stray backslash before the template literal


def test_regex_escape_kept_literally():
    calls = parse_tool_calls(_fence(REGEX_ESCAPE_CALL))
    assert calls == [{"name": "search_text", "arguments": {"query": "require\\|module\\.exports"}}]


def test_extra_closing_brace_still_parses():
    # cycle 3, extract-helpers round 3: 8 valid edits each ending in "}}}".
    body = (r'{"name":"search_replace","arguments":{"path":"blogtool/tags.py",'
            r'"old_string":"import re\n","new_string":"from blogtool.textutil import slugify\n"}}}')
    calls = parse_tool_calls(_fence(body))
    assert calls[0]["name"] == "search_replace"
    assert calls[0]["arguments"]["new_string"] == "from blogtool.textutil import slugify\n"


def test_dangling_key_before_closing_braces_still_parses():
    body = (r'{"name":"search_replace","arguments":{"path":"t.py","old_string":"a\n",'
            r'"new_string":"    return {k: sorted(v) for k, v in index.items()}","}}}')
    calls = parse_tool_calls(_fence(body))
    assert calls[0]["name"] == "search_replace"
    assert calls[0]["arguments"]["new_string"].endswith("index.items()}")


def test_unrepairable_call_is_reported_not_dropped():
    bad = '{"name":"search_replace","arguments":{"path":"a.py","old_string":"x = ["a"]","new_string":"y"}}'
    calls = parse_tool_calls(_fence(bad))
    assert calls[0]["name"] == "__malformed__"


def test_repair_json_escapes_only_touches_invalid_escapes():
    assert repair_json_escapes(r'"a\nb \" \\ A"') == r'"a\nb \" \\ A"'
    assert repair_json_escapes(r'"\$HOME \'x\' \d"') == r'"$HOME ' + "'x'" + r' \\d"'


def _read(round_no: int, path: str, body: str = "x") -> TranscriptEntry:
    return TranscriptEntry(round_no, "read_file", {"path": path}, f"{path}\n1| {body}", True)


def test_working_set_keeps_every_parallel_read_and_drops_stale_ones():
    entries = [_read(1, f"f{i}.py") for i in range(6)]
    entries.append(TranscriptEntry(2, "search_replace", {"path": "f0.py"}, "Edited f0.py", True))
    entries.append(TranscriptEntry(2, "run_command", {"command": "pytest"}, "exit 0", True))
    keep = working_set_indices(entries)
    assert keep == {1, 2, 3, 4, 5, 7}  # f0.py edited after its read: stale; 7 = latest test run
    text = format_transcript(entries)
    for i in range(1, 6):
        assert f"f{i}.py\n1| x" in text


def test_research_status_flags_rereads_and_repeated_failures():
    first = [_read(1, "inventory.py")]
    again = first + [_read(2, "inventory.py")]
    status = build_research_status(again)
    assert "Already read" in status and "MUST be EXECUTE" in status

    bad = TranscriptEntry(3, "__malformed__", {"raw": '{"path":"src/lib/format.js"'}, "Malformed", False)
    status = build_research_status(again + [bad, bad])
    assert "src/lib/format.js" in status and "path fence" in status


def test_latest_test_output_survives_later_rounds():
    fail = TranscriptEntry(7, "run_command", {"command": "node --test"}, "exit 1\n' [ ] x' !== '[ ] x'", False)
    later = [_read(8, f"f{i}.js") for i in range(6)]
    text = format_transcript([fail] + later)
    assert "' [ ] x' !== '[ ] x'" in text


def test_green_tests_after_last_edit_say_finish():
    entries = [
        _read(1, "a.py"),
        TranscriptEntry(2, "write_file", {"path": "a.py"}, "Overwrote a.py", True),
        TranscriptEntry(3, "run_command", {"command": "python -m pytest -q"}, "exit 0\n3 passed", True),
    ]
    assert "FINISH NOW" in build_research_status(entries)
    red = entries[:2] + [TranscriptEntry(3, "run_command", {"command": "python -m pytest -q"}, "exit 1", False)]
    assert "FINISH NOW" not in build_research_status(red)


def test_reread_after_own_edit_is_not_flagged():
    entries = [
        _read(1, "a.js"),
        TranscriptEntry(2, "write_file", {"path": "a.js"}, "Overwrote a.js", True),
        _read(3, "a.js"),
    ]
    assert "MUST be EXECUTE" not in build_research_status(entries)


def test_research_status_quotes_hits_when_search_repeats_without_edits():
    hits = "README.md:3: Use `calc_total(items, tax_rate)`\ntests/test_pricing.py:8: def test_calc_total_with_tax():"
    search = lambda r: TranscriptEntry(r, "search_text", {"query": "calc_total"}, hits, True)
    entries = [_read(1, "README.md"), search(2), search(3)]
    status = build_research_status(entries)
    assert "You already searched 'calc_total'" in status
    assert "tests/test_pricing.py:8" in status and "MUST edit" in status

    edited = entries[:2] + [TranscriptEntry(2, "search_replace", {"path": "README.md"}, "Edited", True), search(3)]
    assert "already searched" not in build_research_status(edited)


def test_workspace_refuses_escape_and_unlisted_commands(tmp_path: Path):
    ws = Workspace(tmp_path)
    ok, msg = ws.run("read_file", {"path": "../secret.txt"})
    assert not ok and "escapes workspace" in msg
    ok, msg = ws.run("run_command", {"command": "del /s *.py"})
    assert not ok and "refused" in msg
    ok, msg = ws.run("run_command", {"command": "python -c \"print(1)\" && echo hi"})
    assert not ok and "refused" in msg
