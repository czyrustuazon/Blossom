"""
Host-side checks that tell the coder what it cannot see in its own edits.

Each one answers a failure seen in the refactor-eval transcripts (see tools/eval/TRAINING.md):
  - syntax_error_note:  an edit left a file that does not parse.
  - GreenTracker:       tests passed, a later edit broke them; show exactly what changed since.
  - near_miss_hint:     search_replace old_string not found; show the file's real closest text.

Mirrored in the extension (src/agent/hostChecks.ts). Pure functions except for `node --check`.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

_OFF = {"0", "false", "no", "off"}


def flag(name: str) -> bool:
    """
    BLOSSOM_EVAL_<NAME>=0 turns one host check off; BLOSSOM_EVAL_HARDEN=0 turns all of them off
    unless a check is switched on by name (for A/B runs of the whole set against the old loop).
    """
    default = os.getenv("BLOSSOM_EVAL_HARDEN", "1")
    return os.getenv(f"BLOSSOM_EVAL_{name}", default).strip().lower() not in _OFF


# ------------------------------------------------------------------ syntax after an edit
_NODE_EXTS = {".js", ".mjs", ".cjs"}
_NODE_LOC_RE = re.compile(r":(\d+)\s*$")


def _python_syntax(rel: str, text: str) -> str:
    try:
        compile(text, rel, "exec")
    except SyntaxError as exc:
        line = (exc.text or "").rstrip("\n")
        caret = " " * max(0, (exc.offset or 1) - 1) + "^" if line else ""
        return f"{rel}:{exc.lineno}: SyntaxError: {exc.msg}\n    {line}\n    {caret}".rstrip()
    except ValueError as exc:  # e.g. null bytes
        return f"{rel}: {exc}"
    return ""


def _json_syntax(rel: str, text: str) -> str:
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        lines = text.splitlines()
        shown = lines[exc.lineno - 1] if 0 < exc.lineno <= len(lines) else ""
        return f"{rel}:{exc.lineno}: invalid JSON: {exc.msg}\n    {shown}".rstrip()
    return ""


def _node_syntax(rel: str, path: Path, root: Path) -> str:
    try:
        proc = subprocess.run(["node", "--check", str(path)], cwd=root, capture_output=True, text=True,
                              timeout=20, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return ""  # no node here: nothing to say
    if proc.returncode == 0:
        return ""
    err = [ln for ln in proc.stderr.splitlines() if ln.strip()]
    message = next((ln.strip() for ln in err if ln.startswith("SyntaxError")), "")
    if not message:
        return ""  # not a parse error (e.g. node could not start); the tests will tell
    lineno = ""
    code = ""
    for i, ln in enumerate(err):
        m = _NODE_LOC_RE.search(ln)
        if m and str(path.name) in ln:
            lineno = m.group(1)
            code = "\n".join(f"    {x}" for x in err[i + 1:i + 3] if not x.startswith("SyntaxError"))
            break
    return f"{rel}:{lineno}: {message}\n{code}".rstrip()


def syntax_error_note(root: Path, rel: str) -> str:
    """'' when the file parses (or its type is not checked); else 'path:line: error' + the line."""
    path = root / rel
    if not path.is_file():
        return ""
    suffix = path.suffix.lower()
    if suffix not in {".py", ".json"} | _NODE_EXTS:
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""
    if suffix == ".py":
        return _python_syntax(rel, text)
    if suffix == ".json":
        return _json_syntax(rel, text)
    return _node_syntax(rel, path, root)


def syntax_warning(note: str) -> str:
    return ("SYNTAX ERROR — this file no longer parses after your edit. Fix this line before anything "
            "else (compare it character by character with how it was: brackets, colons, quotes):\n" + note)


# ------------------------------------------------------------------ changes since green
class GreenTracker:
    """
    Remembers how each edited file looked the last time the tests passed.

    Cycle 11, rename-symbol: green after round 2; a round-4 search_replace turned
    `def test_calc_total_with_tax()` into `def test_compute_order_total_with_tax`. The coder saw
    the SyntaxError but read the line as valid for 12 rounds. A two-line diff against the last
    green state shows the lost `()` directly.

    Usage: before_edit(rel) before every write; mark_green(round) when a test run passes;
    regression_note() when a test run fails.
    """

    MAX_DIFF_LINES = 60
    MAX_FILE_DIFF_LINES = 24

    def __init__(self, read: Callable[[str], str | None]):
        self._read = read            # rel -> current text, or None when the file does not exist
        self.green_round = 0         # 0 = the tests have not passed yet in this run
        self._base: dict[str, str | None] = {}

    def mark_green(self, round_no: int) -> None:
        self.green_round = round_no
        self._base = {}

    def before_edit(self, rel: str) -> None:
        rel = str(rel or "").replace("\\", "/").lstrip("/")
        if self.green_round and rel and rel not in self._base:
            self._base[rel] = self._read(rel)  # unchanged since green, so this IS its green content

    def diff(self) -> str:
        # Created/deleted files first (one line each), then each changed file's diff with its
        # own cap, so one large rewrite cannot push the other files out of view.
        whole: list[str] = []
        diffs: list[str] = []
        for rel in sorted(self._base):
            old, new = self._base[rel], self._read(rel)
            if old == new:
                continue
            if old is None:
                whole.append(f"+++ {rel} (created since the tests passed, {len((new or '').splitlines())} lines)")
                continue
            if new is None:
                whole.append(f"--- {rel} (deleted since the tests passed)")
                continue
            lines = [ln.rstrip("\n") for ln in difflib.unified_diff(
                old.splitlines(), new.splitlines(), f"{rel} (when the tests passed)", f"{rel} (now)",
                n=1, lineterm="")]
            if len(lines) > self.MAX_FILE_DIFF_LINES:
                more = len(lines) - self.MAX_FILE_DIFF_LINES
                lines = lines[:self.MAX_FILE_DIFF_LINES] + [f"... ({more} more diff lines in {rel} not shown)"]
            diffs.extend(lines)
        if len(diffs) > self.MAX_DIFF_LINES:
            more = len(diffs) - self.MAX_DIFF_LINES
            diffs = diffs[:self.MAX_DIFF_LINES] + [f"... ({more} more diff lines not shown)"]
        return "\n".join(whole + diffs)

    def regression_note(self) -> str:
        """Text to append to a FAILED test result; '' when the tests never passed or nothing changed."""
        if not self.green_round:
            return ""
        diff = self.diff()
        if not diff:
            return ""
        return (f"[HOST] These tests PASSED at round {self.green_round}. Everything changed in the files "
                "since then ('-' = when they passed, '+' = now):\n"
                f"{diff}\n"
                "The failure comes from these changes. Compare each '+' line with its '-' line character "
                "by character (brackets, colons, quotes, indentation) before looking anywhere else.")


# ------------------------------------------------------------------ dropped punctuation
_WORD_RE = re.compile(r"\w+")
_PUNCT_NAMES = {"(": "open parenthesis", ")": "close parenthesis", "[": "open bracket", "]": "close bracket",
                "{": "open brace", "}": "close brace", ":": "colon", ",": "comma", ";": "semicolon",
                '"': "double quote", "'": "single quote", ".": "dot", "=": "equals sign"}


def punctuation_in_words(chars: str) -> str:
    """'()' -> 'open parenthesis, close parenthesis'. The coder read `removed: ()` as 'the colon'."""
    return ", ".join(_PUNCT_NAMES.get(ch, repr(ch)) for ch in chars)


def restore_dropped_punctuation(old: str, new: str) -> str | None:
    """
    new_string with the punctuation of old_string put back on every rename-shaped line that
    lost some (same number of words, some changed, punctuation only removed). None = no such line.

    rw-on2, rename-symbol round 12 (2026-11-21): shown "removed: ()", the coder concluded "the
    colon was removed", then judged `def test_compute_order_total_with_tax:` "fine syntactically".
    It cannot see the missing characters, so the host puts them back (and only keeps the result
    when the file parses again; see the loop).
    """
    old_lines, new_lines = old.splitlines(), new.splitlines()
    if not old_lines or len(old_lines) != len(new_lines):
        return None
    out, changed = [], False
    for o, n in zip(old_lines, new_lines):
        wo, wn = _WORD_RE.findall(o), _WORD_RE.findall(n)
        po, pn = re.sub(r"[\w\s]", "", o), re.sub(r"[\w\s]", "", n)
        it = iter(po)
        if wo != wn and len(wo) == len(wn) and len(pn) < len(po) and all(ch in it for ch in pn):
            words = iter(wn)
            rebuilt = _WORD_RE.sub(lambda _m: next(words), o)   # old line's shape, new line's words
            lead = n[:len(n) - len(n.lstrip())]                 # keep the new line's own indentation
            out.append(lead + rebuilt.lstrip())
            changed = True
        else:
            out.append(n)
    if not changed:
        return None
    return "\n".join(out) + ("\n" if new.endswith("\n") else "")


# ------------------------------------------------------------------ old_string not found
def near_miss_hint(text: str, old: str, max_lines: int = 12) -> str:
    """
    The file's real text closest to a search_replace old_string that did not match.

    12 of 30 misses in the 2026-11-20 runs were `def test_calc_total_with_tax:` for a line that
    reads `def test_calc_total_with_tax():`; the rest were spacing, escaping or stale content.
    Showing the exact line lets the coder copy it instead of guessing again.
    """
    lines = text.splitlines()
    old_lines = [ln for ln in old.splitlines() if ln.strip()]
    if not lines or not old_lines:
        return ""
    stripped = [ln.strip() for ln in lines]
    first = difflib.get_close_matches(old_lines[0].strip(), stripped, n=1, cutoff=0.6)
    if not first:
        return ""
    start = stripped.index(first[0])
    span = min(len(old.splitlines()), max_lines)
    block = lines[start:start + span]
    where = f"line {start + 1}" if span == 1 else f"lines {start + 1}-{start + len(block)}"
    return (f"Closest text in the file ({where}) — it differs from your old_string. Copy it EXACTLY "
            "(every bracket, quote and space) if this is what you meant:\n" + "\n".join(block))
