"""Regression tests for the headless Blossom Assistant agent loop (blossom_eval.agent_loop).

The malformed tool calls below are verbatim from Blossom's own replies during the
project-refactor training cycles.
"""

from __future__ import annotations

from pathlib import Path

from blossom_eval.agent_loop import (
    TranscriptEntry,
    Workspace,
    balance_braces,
    claims_unrun_work,
    build_research_status,
    build_round_prompt,
    format_transcript,
    green_idle_rounds,
    parse_tool_calls,
    repair_json_escapes,
    repair_unescaped_quotes,
    run_agent,
    strip_tool_calls,
    wants_verify_push,
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


# cycle 5, extract-helpers round 4: one bare quote (after `[\\s-]+`) inside Python code.
UNESCAPED_QUOTE_CALL = (
    r'{"name":"search_replace","arguments":{"path":"blogtool/tags.py","old_string":"import re\n\n\n'
    r'def _slugify(text):\n    # same rules as posts._slugify\n    text = text.strip().lower()\n'
    r'    text = re.sub(r\"[^a-z0-9\\s-]\", \"\", text)\n    text = re.sub(r\"[\\s-]+", \"-\", text)\n'
    r'    return text.strip(\"-\")\n","new_string":"from blogtool.textutil import slugify\n"}}'
)


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


def test_bare_quote_inside_code_is_repaired():
    calls = parse_tool_calls(_fence(UNESCAPED_QUOTE_CALL))
    assert [c["name"] for c in calls] == ["search_replace"]
    old = calls[0]["arguments"]["old_string"]
    assert 'text = re.sub(r"[\\s-]+", "-", text)' in old
    assert calls[0]["arguments"]["new_string"] == "from blogtool.textutil import slugify\n"


def test_stray_paren_before_closing_braces_still_parses():
    # Cycle 7, globals-to-di round 12 (tail verbatim).
    call = ('{"name":"write_file","arguments":{"path":"tests/test_notifier.py","content":"assert SmsSender('
            'dry_settings, out).send_sms(\\n    number=\\"1\\",\\n    text=\\"x\\"\\n) == \\"dry-run\\"\\n")}}')
    calls = parse_tool_calls(_fence(call))
    assert [c["name"] for c in calls] == ["write_file"]
    assert calls[0]["arguments"]["content"].endswith('== "dry-run"\n')


def test_double_escaped_content_is_decoded_once():
    # Cycle 7, split-module round 15 (start verbatim): \\n and \\\" written for \n and \".
    call = (r'{"name":"write_file","arguments":{"path":"inventory/reports.py","content":"\"\"\"Report generation '
            r'and restock listing.\"\"\"\\nfrom .models import Item\\n\\ndef format_report(items) -> str:\\n'
            r'    lines = [f\\\"{1:<8}\\\"]\\n    return \\\"\\\\n\\\".join(lines)\\n"}}')
    content = parse_tool_calls(_fence(call))[0]["arguments"]["content"]
    assert content.splitlines()[1] == "from .models import Item"
    assert '    lines = [f"{1:<8}"]' in content and 'return "\\n".join(lines)' in content
    # Real multi-line content with an escaped \n inside code is left alone.
    ok = r'{"name":"write_file","arguments":{"path":"a.py","content":"x = \"a\\nb\"\ny = \"c\\nd\"\n"}}'
    assert parse_tool_calls(_fence(ok))[0]["arguments"]["content"] == 'x = "a\\nb"\ny = "c\\nd"\n'


def test_missing_closing_brace_is_balanced():
    # Cycle 8, split-module round 5 (shape verbatim): bare tool_call lines, first call one "}" short.
    reply = ('tool_call\n{"name":"write_file","arguments":{"path":"inventory/reports.py","content":'
             '"def restock_list(items):\\n    return [i.sku for i in items if i.qty < 5]"}\n'
             'tool_call\n{"name":"run_command","arguments":{"command":"python -m pytest -q"}}')
    calls = parse_tool_calls(reply)
    assert [c["name"] for c in calls] == ["write_file", "run_command"]
    assert balance_braces('{"a":{"b":"}"}') == '{"a":{"b":"}"}}'  # brace inside a string ignored


def test_fabricated_summary_without_tool_calls_is_caught():
    # Cycle 8, globals-to-di round 2: summary of six changed files + "All tests pass", zero tools.
    summary = ("### Summary\n- **Created** `notifier/config.py`\n- **Edited** `notifier/mailer.py`\n"
               "- **Deleted** `notifier/settings.py`\nAll tests pass.")
    assert claims_unrun_work(summary, [_read(1, "notifier/mailer.py")])
    done = TranscriptEntry(2, "write_file", {"path": "notifier/config.py", "content": "x"}, "Created", True)
    assert not claims_unrun_work(summary, [done])
    assert not claims_unrun_work("I updated my understanding: the module is fine.", [])


def test_quote_repair_leaves_valid_json_alone():
    valid = '{"name":"write_file","arguments":{"path":"a.py","content":"x = \\"a\\", \\"b\\"\\n"}}'
    assert repair_unescaped_quotes(valid) == valid


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
        # search_replace shows no resulting file, so a re-read after it is legitimate.
        # (A whole-file write_file is shown verbatim — re-reading that IS flagged.)
        TranscriptEntry(2, "search_replace", {"path": "a.js"}, "Edited a.js", True),
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
    ok, msg = ws.run("run_command", {"command": "python -c \"print(1)\" 2>&1 > out.txt"})
    assert not ok and "refused" in msg


def test_shell_characters_inside_quotes_are_allowed(tmp_path: Path):
    # Cycle 7, split-module: `python -c "...; print(...)"` refused for the quoted ";".
    ok, msg = Workspace(tmp_path).run("run_command", {"command": 'python -c "import os; print(7*6)"'})
    assert ok and "42" in msg


def test_edit_rounds_without_a_test_run_get_a_nudge():
    test = TranscriptEntry(8, "run_command", {"command": "python -m pytest -q"}, "exit 2", False)
    edits = [TranscriptEntry(r, "write_file", {"path": "tests/t.py", "content": "x"}, "Overwrote", True) for r in (9, 11, 15)]
    assert "run them NOW" in build_research_status([test, *edits])
    assert "run them NOW" not in build_research_status([test, *edits[:2]])


def test_trailing_stderr_merge_is_allowed(tmp_path: Path):
    # Cycle 4: `npm test 2>&1` was refused by the eval host but runs in the extension.
    ok, msg = Workspace(tmp_path).run("run_command", {"command": "python -c \"print(42)\" 2>&1"})
    assert ok and "42" in msg


def test_write_before_read_in_same_round_is_refused(tmp_path: Path):
    # Cycle 4, cjs-to-esm round 1: read_file + write_file in one reply overwrote
    # package.json with a guessed {"name": "task-manager"}.
    (tmp_path / "package.json").write_text('{"name": "real"}', encoding="utf-8")
    ws = Workspace(tmp_path)
    assert ws.run("read_file", {"path": "package.json"})[0]
    ok, msg = ws.run("write_file", {"path": "package.json", "content": '{"name": "task-manager"}'})
    assert not ok and "not read it" in msg
    assert (tmp_path / "package.json").read_text(encoding="utf-8") == '{"name": "real"}'
    ws.end_round()
    assert ws.run("write_file", {"path": "package.json", "content": '{"name": "real", "type": "module"}'})[0]


def test_own_whole_file_writes_stay_in_view_as_current_content():
    # Cycle 5, cjs-to-esm round 5: after round-2 writes the transcript only said
    # "Overwrote src/index.js (169 chars)" and Blossom re-read all six files.
    entries = [TranscriptEntry(1, "read_file", {"path": "src/index.js"}, "src/index.js (lines 1-1 of 1)\n1| old", True)]
    for r in range(2, 6):  # push the write out of the full-transcript tail
        entries.append(TranscriptEntry(r, "write_file", {"path": "src/index.js" if r == 2 else f"f{r}.js",
                                                          "content": "export const v = 1;\n" if r == 2 else "x"},
                                       "Overwrote", True))
        entries += [TranscriptEntry(r, "search_text", {"query": f"q{r}{k}"}, "No matches.", True) for k in range(4)]
    entries.append(TranscriptEntry(5, "run_command", {"command": "npm test"}, "exit 1", False))
    text = format_transcript(entries)
    assert "1| export const v = 1;" in text
    assert "1| old" not in text  # the pre-write read is stale
    assert "src/index.js" in build_research_status(entries + [
        TranscriptEntry(6, "read_file", {"path": "src/index.js"}, "src/index.js\n1| export const v = 1;", True)])


def test_green_tests_with_leftover_hits_quote_them_instead_of_saying_finish():
    # Cycle 5, rename-symbol rounds 6-16: green tests + one leftover hit = 10 rounds of re-searching.
    entries = [
        TranscriptEntry(5, "search_replace", {"path": "shopkit/__init__.py"}, "Edited", True),
        TranscriptEntry(5, "run_command", {"command": "python -m pytest -q"}, "exit 0\n3 passed", True),
        TranscriptEntry(6, "search_text", {"query": "calc_total"},
                        "tests/test_pricing.py:8: def test_calc_total_with_tax():", True),
    ]
    status = build_research_status(entries)
    assert "def test_calc_total_with_tax" in status and "FINISH NOW" not in status
    clean = entries[:2] + [TranscriptEntry(6, "search_text", {"query": "calc_total"}, "No matches.", True)]
    assert "FINISH NOW" in build_research_status(clean)
    # Cycle 6: the old name's empty result must be listed next to the new name's hits.
    both = clean + [TranscriptEntry(6, "search_text", {"query": "compute_order_total"},
                                    "shopkit/pricing.py:9: def compute_order_total(items):", True)]
    status = build_research_status(both)
    assert 'search "calc_total": No matches' in status and "def compute_order_total" in status


def test_tool_call_missing_opening_fence_still_runs():
    # Cycle 5, split-module final reply, verbatim.
    reply = 'tool_call\n{"name":"delete_file","arguments":{"path":"inventory.py"}}```'
    assert parse_tool_calls(reply) == [{"name": "delete_file", "arguments": {"path": "inventory.py"}}]
    assert strip_tool_calls(reply) == ""
    # A cut-off final fence is closed too; prose mentioning tool_call is left alone.
    assert parse_tool_calls(_fence('{"name":"list_dir","arguments":{}}')[:-3])[0]["name"] == "list_dir"
    assert parse_tool_calls("I will use a tool_call next.") == []


def test_finishing_with_unverified_edits_gets_one_verify_push():
    edit = TranscriptEntry(2, "write_file", {"path": "a.py", "content": "x"}, "Created", True)
    assert wants_verify_push([edit])
    green = TranscriptEntry(3, "run_command", {"command": "python -m pytest -q"}, "exit 0", True)
    assert not wants_verify_push([edit, green])
    assert not wants_verify_push([TranscriptEntry(1, "read_file", {"path": "a.py"}, "a", True)])


def test_repeated_search_with_hits_offers_exact_edit_templates():
    # Cycle 8, rename-symbol rounds 7-14: knew the fix, misquoted the line, kept searching.
    hit = "tests/test_pricing.py:8: def test_calc_total_with_tax():"
    entries = [_read(1, "tests/test_pricing.py"),
               TranscriptEntry(6, "search_replace", {"path": "shopkit/cart.py"}, "Edited", True),
               TranscriptEntry(7, "search_text", {"query": "calc_total"}, hit, True),
               TranscriptEntry(8, "search_text", {"query": "calc_total"}, hit, True)]
    status = build_research_status(entries)
    template = '"old_string": "def test_calc_total_with_tax():"'
    assert template in status and '"path": "tests/test_pricing.py"' in status
    # The template is itself a valid tool call once new_string is filled in.
    call = status[status.index("```tool_call"):]
    assert parse_tool_calls(call)[0]["name"] == "search_replace"


def test_repeated_empty_search_is_flagged():
    # Cycle 6, cjs-to-esm rounds 5-8: `require` searched again and again, always "No matches."
    edit = TranscriptEntry(2, "search_replace", {"path": "src/index.js"}, "Edited", True)
    empty = lambda r: TranscriptEntry(r, "search_text", {"query": "require"}, "No matches.", True)
    status = build_research_status([edit, empty(5), empty(6)])
    assert "do NOT search it again" in status


def test_stale_prose_is_dropped_once_tests_are_green():
    # Cycle 6, cjs-to-esm: round-8 prose "npm test failed" kept showing after green runs.
    edit = TranscriptEntry(9, "search_replace", {"path": "src/lib/format.js"}, "Edited", True)
    green = TranscriptEntry(10, "run_command", {"command": "npm test"}, "exit 0\npass 2", True)
    stale = "npm test failed with an import error in src/taskList.js"
    assert stale not in build_round_prompt("BASE", [edit, green], 11, 16, stale)
    assert stale in build_round_prompt("BASE", [edit], 10, 16, stale)


def test_green_idle_rounds_counts_rounds_after_first_green_test():
    # Cycle 6, globals-to-di: green at round 7, then 8 rounds of re-reading and re-testing.
    edit = TranscriptEntry(7, "write_file", {"path": "notifier/sms.py", "content": "x"}, "Created", True)
    green = TranscriptEntry(7, "run_command", {"command": "python -m pytest -q"}, "exit 0", True)
    reads = [TranscriptEntry(r, "read_file", {"path": "notifier/sms.py"}, "x", True) for r in (8, 9)]
    assert green_idle_rounds([edit, green]) == 0
    assert green_idle_rounds([edit, green, reads[0]]) == 1
    assert green_idle_rounds([edit, green, *reads]) == 2
    red = TranscriptEntry(7, "run_command", {"command": "python -m pytest -q"}, "exit 1", False)
    assert green_idle_rounds([edit, red, *reads]) == 0


def test_deleted_files_last_read_stays_in_view():
    # Cycle 6, split-module: inventory.py deleted, its read dropped as stale, code rewritten from memory.
    read = TranscriptEntry(1, "read_file", {"path": "inventory.py"}, "inventory.py\n1| class Item:  # sku, unit_cost", True)
    gone = TranscriptEntry(2, "delete_file", {"path": "inventory.py"}, "Deleted inventory.py", True)
    noise = [TranscriptEntry(r, "search_text", {"query": f"q{r}{k}"}, "No matches.", True) for r in (3, 4) for k in range(3)]
    text = format_transcript([read, gone, *noise])
    assert "class Item:  # sku, unit_cost" in text and "DELETED since" in text


def test_delete_is_skipped_when_an_edit_in_the_same_reply_failed(tmp_path: Path, monkeypatch):
    (tmp_path / "inventory.py").write_text("class Item: pass\n", encoding="utf-8")
    bad_write = _fence('{"name":"write_file","arguments":{"path":"inventory/models.py","content":""""Doc."""\n"}}')
    delete = _fence('{"name":"delete_file","arguments":{"path":"inventory.py"}}')
    replies = iter([{"content": delete + "\n" + bad_write, "reasoning": "", "steps": [], "source": "t"},
                    {"content": "Done.", "reasoning": "", "steps": [], "source": "t"}])
    monkeypatch.setattr("blossom_eval.agent_loop._ask", lambda prompt, timeout_sec: next(replies))
    log = run_agent("split it", tmp_path, max_rounds=3)
    assert (tmp_path / "inventory.py").exists()
    assert any(e.name == "delete_file" and "Not deleted" in e.result for e in log.transcript)


def test_new_files_and_own_writes_need_no_read(tmp_path: Path):
    ws = Workspace(tmp_path)
    assert ws.run("write_file", {"path": "src/new.js", "content": "a"})[0]
    assert ws.run("write_file", {"path": "src/new.js", "content": "b"})[0]
