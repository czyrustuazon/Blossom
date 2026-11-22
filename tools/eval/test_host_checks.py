"""Host checks built from failures in the refactor-eval transcripts (cycle 11 and the 2026-11-20 A/B runs)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from blossom_eval.host_checks import (
    GreenTracker, near_miss_hint, php_balance_error, regex_fallback, syntax_error_note, syntax_warning,
)

# cycle 11, rename-symbol: the test file after the coder's round-4 search_replace.
BROKEN_TEST = (
    "from decimal import Decimal\n\n"
    "from shopkit import compute_order_total\n\n\n"
    "def test_compute_order_total_with_tax:\n"
    "    assert compute_order_total([{'price': 10, 'qty': 2}], 0.1) == Decimal('22.00')\n"
)
GOOD_TEST = BROKEN_TEST.replace("with_tax:", "with_tax():")


def test_python_syntax_error_names_the_line(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pricing.py").write_text(BROKEN_TEST, encoding="utf-8")
    note = syntax_error_note(tmp_path, "tests/test_pricing.py")
    assert note.startswith("tests/test_pricing.py:6: SyntaxError")
    assert "def test_compute_order_total_with_tax:" in note
    assert "no longer parses" in syntax_warning(note)
    (tmp_path / "tests" / "test_pricing.py").write_text(GOOD_TEST, encoding="utf-8")
    assert syntax_error_note(tmp_path, "tests/test_pricing.py") == ""


def test_json_and_unchecked_files(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"type": "module",}\n', encoding="utf-8")
    assert syntax_error_note(tmp_path, "package.json").startswith("package.json:1: invalid JSON")
    (tmp_path / "README.md").write_text("def broken:\n", encoding="utf-8")
    assert syntax_error_note(tmp_path, "README.md") == ""
    assert syntax_error_note(tmp_path, "missing.py") == ""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_javascript_syntax_error(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"type": "module"}\n', encoding="utf-8")
    (tmp_path / "a.js").write_text("export function f( {\n  return 1;\n}\n", encoding="utf-8")
    note = syntax_error_note(tmp_path, "a.js")
    assert note.startswith("a.js:") and "SyntaxError" in note
    (tmp_path / "a.js").write_text("export function f() {\n  return 1;\n}\n", encoding="utf-8")
    assert syntax_error_note(tmp_path, "a.js") == ""


def _tracker(tmp_path: Path) -> GreenTracker:
    def read(rel: str) -> str | None:
        p = tmp_path / rel
        return p.read_text(encoding="utf-8") if p.is_file() else None
    return GreenTracker(read)


def test_regression_note_shows_only_what_changed_since_green(tmp_path: Path):
    test_file = tmp_path / "test_pricing.py"
    test_file.write_text(GOOD_TEST.replace("test_compute_order_total", "test_calc_total"), encoding="utf-8")
    tracker = _tracker(tmp_path)

    tracker.before_edit("test_pricing.py")          # before the first green: nothing to compare with
    assert tracker.regression_note() == ""

    tracker.mark_green(2)
    assert tracker.regression_note() == ""          # green and unchanged
    tracker.before_edit("test_pricing.py")
    test_file.write_text(BROKEN_TEST, encoding="utf-8")
    note = tracker.regression_note()
    assert "PASSED at round 2" in note
    assert "-def test_calc_total_with_tax():" in note
    assert "+def test_compute_order_total_with_tax:" in note
    assert "from decimal import Decimal" not in note  # untouched lines stay out

    test_file.write_text(GOOD_TEST, encoding="utf-8")
    tracker.mark_green(5)                            # fixed: the next failure diffs against round 5
    assert tracker.regression_note() == ""


def test_regression_note_reports_created_and_deleted_files_and_caps_the_diff(tmp_path: Path):
    (tmp_path / "old.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "big.py").write_text("\n".join(f"a{i} = {i}" for i in range(200)) + "\n", encoding="utf-8")
    tracker = _tracker(tmp_path)
    tracker.mark_green(3)
    for rel in ("old.py", "new.py", "big.py"):
        tracker.before_edit(rel)
    (tmp_path / "old.py").unlink()
    (tmp_path / "new.py").write_text("y = 2\nz = 3\n", encoding="utf-8")
    (tmp_path / "big.py").write_text("\n".join(f"b{i} = {i}" for i in range(200)) + "\n", encoding="utf-8")
    note = tracker.regression_note()
    assert "--- old.py (deleted since the tests passed)" in note
    assert "+++ new.py (created since the tests passed, 2 lines)" in note
    assert "more diff lines in big.py not shown" in note
    assert len(note.splitlines()) < GreenTracker.MAX_DIFF_LINES + 8


def test_near_miss_shows_the_real_line():
    # 12 of 30 old_string misses on 2026-11-20: the coder dropped the () from this line.
    hint = near_miss_hint(GOOD_TEST.replace("test_compute_order_total", "test_calc_total"),
                          "def test_calc_total_with_tax:")
    assert "line 6" in hint and hint.endswith("def test_calc_total_with_tax():")


def test_near_miss_for_a_block_and_for_nothing_similar():
    text = "import re\n\n\ndef _slugify(text):\n    text = text.strip().lower()\n    return text\n\nX = 1\n"
    hint = near_miss_hint(text, "def _slugify(text):\n  text = text.strip().lower()\n  return text")
    assert "lines 4-6" in hint and "    text = text.strip().lower()" in hint
    assert near_miss_hint(text, "class Totally: unrelated = True") == ""
    assert near_miss_hint("", "x") == ""


# ------------------------------------------------------------------ wired into the loop
import json  # noqa: E402

from blossom_eval.agent_loop import Workspace, run_agent  # noqa: E402

FENCE = "`" * 3


def _call(name: str, **arguments) -> str:
    return f"{FENCE}tool_call\n{json.dumps({'name': name, 'arguments': arguments})}\n{FENCE}\n"


def _reply(text: str) -> dict:
    return {"content": text, "reasoning": "", "steps": [], "source": "test"}


def _shop(tmp_path: Path) -> None:
    (tmp_path / "shop.py").write_text("def calc_total(n):\n    return n * 2\n", encoding="utf-8")
    (tmp_path / "test_shop.py").write_text(
        "from shop import calc_total\n\n\ndef test_calc_total_doubles():\n    assert calc_total(2) == 4\n",
        encoding="utf-8")


def test_cycle_11_replay_the_coder_is_shown_what_it_broke(tmp_path: Path, monkeypatch):
    _shop(tmp_path)
    replies = iter([
        _reply(_call("read_file", path="shop.py") + _call("read_file", path="test_shop.py")),
        # A harmless edit: the host runs the tests and they pass (round 2 = last green).
        _reply(_call("search_replace", path="shop.py", old_string="return n * 2", new_string="return 2 * n")),
        # The cycle 11 mistake: the rename drops the ().
        _reply(_call("search_replace", path="test_shop.py", old_string="def test_calc_total_doubles()",
                     new_string="def test_total_doubles")),
        _reply("Done."),
    ])
    monkeypatch.setattr("blossom_eval.agent_loop._ask", lambda prompt, timeout_sec: next(replies))
    monkeypatch.setenv("BLOSSOM_EVAL_PUNCT_REPAIR", "0")  # the path where the host cannot repair it
    log = run_agent("rename the test", tmp_path, max_rounds=4)

    edit = next(e for e in log.transcript if e.round == 3 and e.name == "search_replace")
    assert "removed: ()" in edit.result                      # rename warning
    assert "SYNTAX ERROR" in edit.result and "test_shop.py:4" in edit.result
    host_runs = [e for e in log.transcript if e.name == "run_command" and e.args.get("by") == "host"]
    assert [e.ok for e in host_runs] == [True, False]
    red = host_runs[1].result
    assert "PASSED at round 2" in red
    assert "-def test_calc_total_doubles():" in red and "+def test_total_doubles:" in red
    assert "return 2 * n" not in red                         # the round-2 edit was already green


def test_host_checks_can_be_switched_off_together(tmp_path: Path, monkeypatch):
    _shop(tmp_path)
    replies = iter([
        _reply(_call("read_file", path="test_shop.py")),
        _reply(_call("search_replace", path="shop.py", old_string="return n * 2", new_string="return 2 * n")),
        _reply(_call("search_replace", path="test_shop.py", old_string="def test_calc_total_doubles()",
                     new_string="def test_total_doubles")),
        _reply("Done."),
    ])
    monkeypatch.setattr("blossom_eval.agent_loop._ask", lambda prompt, timeout_sec: next(replies))
    monkeypatch.setenv("BLOSSOM_EVAL_HARDEN", "0")
    log = run_agent("rename the test", tmp_path, max_rounds=4)
    text = "\n".join(e.result for e in log.transcript)
    assert "SYNTAX ERROR" not in text and "PASSED at round" not in text and "removed: ()" not in text


def test_old_string_miss_shows_the_real_line(tmp_path: Path):
    _shop(tmp_path)
    ok, msg = Workspace(tmp_path).run("search_replace", {
        "path": "test_shop.py", "old_string": "def test_calc_total_doubles:", "new_string": "def test_x():"})
    assert not ok and "old_string not found" in msg
    assert msg.endswith("def test_calc_total_doubles():")


def test_unread_overwrite_is_refused_but_shows_the_file(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name": "real"}\n', encoding="utf-8")
    ws = Workspace(tmp_path)
    ok, msg = ws.run("write_file", {"path": "package.json", "content": '{"name": "guess"}'})
    assert not ok and '1| {"name": "real"}' in msg
    assert json.loads((tmp_path / "package.json").read_text(encoding="utf-8")) == {"name": "real"}
    ok, _ = ws.run("write_file", {"path": "package.json", "content": '{"name": "again"}'})
    assert not ok                                             # same round: still refused
    ws.end_round()
    ok, _ = ws.run("write_file", {"path": "package.json", "content": '{"name": "real", "type": "module"}'})
    assert ok                                                 # next round: it has seen the file


def test_malformed_reply_is_asked_again_once(tmp_path: Path, monkeypatch):
    bad = f'{FENCE}tool_call\n{{"name": write_file, "arguments": path=a.py}}\n{FENCE}\n'
    good = _call("write_file", path="a.py", content='x = "hi"\n')
    replies = iter([_reply(bad), _reply(good), _reply("Done.")])
    monkeypatch.setattr("blossom_eval.agent_loop._ask", lambda prompt, timeout_sec: next(replies))
    log = run_agent("write a.py", tmp_path, max_rounds=2)
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == 'x = "hi"\n'
    assert log.rounds[0].get("resampled") is True
    assert not any(e.name == "__malformed__" for e in log.transcript)


def test_host_restores_dropped_punctuation_when_that_makes_the_file_parse(tmp_path: Path, monkeypatch):
    # rw-on2, rename-symbol: told "removed: ()", the coder answered "the colon was removed".
    _shop(tmp_path)
    replies = iter([
        _reply(_call("read_file", path="test_shop.py")),
        _reply(_call("search_replace", path="test_shop.py", old_string="def test_calc_total_doubles():",
                     new_string="def test_total_doubles:")),
        _reply("Done."),
    ])
    monkeypatch.setattr("blossom_eval.agent_loop._ask", lambda prompt, timeout_sec: next(replies))
    log = run_agent("rename the test", tmp_path, max_rounds=4)
    assert "def test_total_doubles():" in (tmp_path / "test_shop.py").read_text(encoding="utf-8")
    edit = next(e for e in log.transcript if e.name == "search_replace")
    assert "HOST FIX" in edit.result and "def test_total_doubles():" in edit.result
    assert "SYNTAX ERROR" not in edit.result
    host_run = next(e for e in log.transcript if e.args.get("by") == "host")
    assert host_run.ok


def test_restore_dropped_punctuation_only_touches_rename_shaped_lines():
    from blossom_eval.host_checks import punctuation_in_words, restore_dropped_punctuation
    assert restore_dropped_punctuation("def test_a():", "def test_b:") == "def test_b():"
    assert restore_dropped_punctuation("    x = old(a)\n", "    x = new a\n") == "    x = new(a)\n"
    assert restore_dropped_punctuation("f(a, b)", "f(a)") is None                  # an argument was removed
    assert restore_dropped_punctuation("x = calc(1)", "x = compute(1)") is None    # nothing dropped
    assert punctuation_in_words("()") == "open parenthesis, close parenthesis"


def test_status_points_at_the_regression_before_older_failures():
    from blossom_eval.agent_loop import build_research_status
    from blossom_eval.agent_loop import TranscriptEntry as E
    entries = [
        E(1, "read_file", {"path": "a.py"}, "a.py (lines 1-1 of 1)\n1| x", True),
        E(2, "write_file", {"path": "a.py", "content": "x"}, "content is required", False),
        E(3, "write_file", {"path": "a.py", "content": "x"}, "content is required", False),
        E(4, "search_replace", {"path": "t.py"}, "Edited t.py", True),
        E(4, "run_command", {"command": "python -m pytest -q", "by": "host"},
          "exit 2\n[HOST] These tests PASSED at round 2. Everything changed ...\n-def t():\n+def t:", False),
    ]
    status = build_research_status(entries)
    assert "PASSED at round 2 and FAIL now" in status and "path fence" not in status


# ---------------------------------------------------------------- php-modernize eval, 2026-11-21

# text_filter.php after the coder's round-5 search_replace of the each() loop: one ')' too many.
PHP_BROKEN = (
    "<?PHP\n"
    "function tag_list($tags)\n"
    "{\n"
    "\t$out = array();\n"
    "\t$parts = explode(',', $tags);\n"
    "\tforeach ($parts as $key => $value))\n"
    "\t{\n"
    "\t\t$out[] = trim($value);\n"
    "\t}\n"
    "\treturn $out;\n"
    "}\n"
    "?>\n"
)


def test_php_syntax_error_names_the_line(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PATH", "")  # no php on PATH: the bracket check must catch it
    (tmp_path / "includes").mkdir()
    (tmp_path / "includes" / "text_filter.php").write_text(PHP_BROKEN, encoding="utf-8")
    note = syntax_error_note(tmp_path, "includes/text_filter.php")
    assert note.startswith("includes/text_filter.php:6: unexpected ')'"), note
    assert "foreach ($parts as $key => $value))" in note
    fixed = PHP_BROKEN.replace("$value))", "$value)")
    (tmp_path / "includes" / "text_filter.php").write_text(fixed, encoding="utf-8")
    assert syntax_error_note(tmp_path, "includes/text_filter.php") == ""


def test_php_balance_ignores_strings_comments_and_html():
    src = (
        "<html><p>(unbalanced html is fine</p>\n"
        "<?php\n"
        "$a = 'a ) in a string'; // and ( in a comment\n"
        "/* { block comment */\n"
        "$b = \"escaped \\\" quote )\";\n"
        "$sql = <<<SQL\nSELECT ( FROM t\nSQL;\n"
        "if ($a) { echo $b; }\n"
        "?>\n<p>)</p>\n"
    )
    assert php_balance_error(src) is None
    assert php_balance_error("<?php\nif ($x) {\n  echo 1;\n") == (2, "'{' is never closed")
    assert php_balance_error("<?php\n$s = 'open;\n")[1].startswith("unterminated")


@pytest.mark.parametrize("query,line,expected", [
    ("each\\(", "while (list($k, $v) = each($parts))", True),                      # escaped paren
    ("mysql_|ereg_|each\\(", "$r = mysql_query($q);", True),                       # alternation
    ("ereg_replace\\\\|eregi\\\\|each\\\\(", "return eregi('x', $e);", True),      # double-escaped grep style
])
def test_regex_shaped_queries_get_a_regex_search(query, line, expected):
    rx = regex_fallback(query)
    assert rx is not None
    assert bool(rx.search(line)) is expected


@pytest.mark.parametrize("query", ["mysql_", "get_magic_quotes", "foo()", "$_GET['id']", "a.b"])
def test_plain_queries_stay_literal(query):
    assert regex_fallback(query) is None


def test_search_text_runs_regex_shaped_query_as_regex(tmp_path: Path):
    from blossom_eval.agent_loop import Workspace

    (tmp_path / "text_filter.php").write_text("<?php\n$p = split(',', $t);\nwhile (list($k,$v) = each($p)) {}\n",
                                               encoding="utf-8")
    ws = Workspace(tmp_path)
    ok, msg = ws.run("search_text", {"query": "each\\(|split\\("})
    assert ok
    assert "LITERAL" in msg and "2 hit(s)" in msg
    assert "text_filter.php:2:" in msg and "text_filter.php:3:" in msg
    ok, msg = ws.run("search_text", {"query": "split("})
    assert msg.startswith("text_filter.php:2:")  # literal hit: unchanged behaviour
