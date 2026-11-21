"""
Headless replica of Blossom Assistant's ChatRouter tool loop, for evaluation.

The VS Code extension (orchestrator.ts / toolProtocol.ts) talks to ChatRouter with ONE
packed user message per round: base prompt + compact tool transcript + an [AGENT LOOP] or
[CONTINUE] block. The model asks for tools with ```tool_call JSON fences; the host runs
them and sends the next round. A round with no tool_call fences ends the turn. Path-labeled
file fences in prose are applied like the extension's Apply step.

This module reproduces that loop against a throwaway copy of a project so multi-file
refactors can be scored by real tests. It is not the extension: rescues such as host
search after a search monologue are not replicated, so scores are a lower bound.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

from .apply import extract_file_writes
from .client import chat_router_url

TOOL_CALL_FENCE_RE = re.compile(r"```tool_call\s*\r?\n([\s\S]*?)```", re.IGNORECASE)
_VALID_ESCAPES = set('\\"/bfnrtu')
_JSON = json.JSONDecoder()
_DANGLING_KEY_RE = re.compile(r'",\s*"(\}+)\s*$')
_STRAY_PAREN_RE = re.compile(r'"\s*\)+\s*(\}+)\s*$')


def repair_json_escapes(text: str) -> str:
    """
    Fix escapes a coder writes that JSON rejects. A backslash before ` ' $ was meant
    to escape a JS/shell character, so drop it (`\\`` -> "`"); before anything else it
    was meant literally (regex "\\s", "a\\|b"), so double it. Mirrors the extension.
    """
    def fix(m: re.Match) -> str:
        nxt = m.group(1)
        if nxt in _VALID_ESCAPES:
            return m.group(0)  # valid pair (\\ \" \n …) stays as is
        if nxt in {"`", "'", "$"}:
            return nxt
        return "\\\\" + nxt

    # Consume escape PAIRS so a valid "\\" is never split and re-read as "\" + next.
    return re.sub(r"\\(.?)", fix, text, flags=re.DOTALL)
FULL_TRANSCRIPT_TAIL = 2
ONE_LINE_MIDDLE = 3
MAX_RESULT_CHARS = 6000
COMMAND_TIMEOUT_SEC = 120

# Commands the eval host will run. Anything else is refused (the model learns from the
# refusal the same way it learns from any failed tool call).
ALLOWED_COMMAND_HEADS = {
    "python", "py", "pytest", "node", "npm", "npx", "dir", "ls", "type", "cat", "git",
}

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache", "_acceptance"}

TOOL_CATALOG = [
    ("list_dir", "path", "List files and folders under a workspace-relative directory."),
    ("read_file", "path*, startLine, endLine",
     "Read a workspace file (optionally a 1-based inclusive line range). Output lines are prefixed 'N| ' for reference only; never include those prefixes in edits."),
    ("search_text", "query*, path, maxResults",
     "Search file contents (literal text, case-insensitive) across the workspace or under path. Returns path:line: text."),
    ("search_replace", "path*, old_string*, new_string*, replace_all",
     "Preferred for EDITING existing files: replace one exact old_string with new_string. old_string must match the file exactly (including whitespace) and be unique unless replace_all."),
    ("write_file", "path*, content*",
     "Create/replace a file. For existing product files prefer search_replace. Content with quotes, "
     "backticks or backslashes must be JSON-escaped — if that fails, put the complete file in a path "
     "fence instead (```lang path=x), which needs no escaping."),
    ("delete_file", "path*", "Delete a workspace file."),
    ("run_command", "command*",
     "Run ONE shell command (tests, python/node probes, git). It already runs in the workspace root: "
     "no `cd … &&` prefix, no `|| true`, no pipes. Example: python -m pytest -q. Returns exit code + output."),
    ("ask_user", "question*, options", "Ask the user to choose between real forks."),
]

FULL_PROFILE_RULES = [
    "Rules:",
    "- Prefer RESEARCH tools before writing product files on non-trivial tasks.",
    "- After search_text, read_file with startLine/endLine around hits (avoid whole-file reads).",
    "- Use search_text to discover related files that must change together.",
    "- You may CREATE/EDIT any path in the workspace (not only the open/attached file). Multi-file = multiple search_replace / write_file / path fences in the same EXECUTE.",
    "- After tool results appear in [AGENT TOOL TRANSCRIPT], continue or finish — do not invent results.",
    "- Approved plans: EXECUTE all planned files in this turn (every path) → VERIFY → talk to the user in prose.",
    "- Prefer multiple ```tool_call fences in one reply for independent reads — the host may run them in parallel.",
    "- Finish by talking to the user in short prose (no ### Summary card; no more tool_call fences).",
]


def native_tools_enabled() -> bool:
    """Native tool calls are opt-in (BLOSSOM_EVAL_NATIVE_TOOLS=1); the fence protocol is the default.
    A/B on 2026-11-20 (3 cycles each): fence 11/15, native 10/15 — no measured gain yet."""
    return os.getenv("BLOSSOM_EVAL_NATIVE_TOOLS", "0").strip().lower() in {"1", "true", "yes", "on"}


_NATIVE_PARAM_TYPES = {"startLine": "integer", "endLine": "integer", "maxResults": "integer",
                       "replace_all": "boolean", "options": "array"}
_NATIVE_DESCRIPTIONS = {
    "write_file": "Create/replace a file with the given COMPLETE content (raw text, exactly as it "
                  "must appear in the file). For existing product files prefer search_replace.",
}


def native_tool_schemas() -> list[dict[str, Any]]:
    """TOOL_CATALOG as OpenAI `tools`; ChatRouter passes them to llama-server on agent rounds."""
    out = []
    for name, arg_spec, desc in TOOL_CATALOG:
        props: dict[str, Any] = {}
        required = []
        for raw in arg_spec.split(","):
            arg = raw.strip()
            if not arg:
                continue
            key = arg.rstrip("*")
            kind = _NATIVE_PARAM_TYPES.get(key, "string")
            props[key] = {"type": kind, "items": {"type": "string"}} if kind == "array" else {"type": kind}
            if arg.endswith("*"):
                required.append(key)
        out.append({"type": "function", "function": {
            "name": name, "description": _NATIVE_DESCRIPTIONS.get(name, desc),
            "parameters": {"type": "object", "properties": props, "required": required},
        }})
    return out


@dataclass
class TranscriptEntry:
    round: int
    name: str
    args: dict[str, Any]
    result: str
    ok: bool


@dataclass
class AgentRunLog:
    rounds: list[dict[str, Any]] = field(default_factory=list)
    transcript: list[TranscriptEntry] = field(default_factory=list)
    final_text: str = ""
    stop_reason: str = ""
    elapsed_sec: float = 0.0
    edits: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- parsing
_BARE_TOOL_CALL_RE = re.compile(r"(^|\n)[ \t]*tool_call[ \t]*\r?\n(?=\s*\{)", re.IGNORECASE)
_FENCE_OPEN_SPLIT_RE = re.compile(r"(```tool_call[ \t]*\r?\n)", re.IGNORECASE)


def normalize_tool_fences(text: str) -> str:
    """
    Restore a tool_call fence that lost its opening backticks (cycle 5, split-module: the
    final reply was `tool_call\\n{"name":"delete_file",…}` + "```" and was taken for a
    finished prose answer), and close a final fence the reply cut off.
    Mirrors normalizeToolFences() in the extension's toolProtocol.ts.
    """
    text = _BARE_TOOL_CALL_RE.sub(lambda m: m.group(1) + "```tool_call\n", text or "")
    # Every fence body must close before the next opener; otherwise the next opener's
    # backticks are taken as this fence's close and that call is lost (cycle 8: two
    # bare `tool_call` lines in a row, the second call vanished).
    parts = _FENCE_OPEN_SPLIT_RE.split(text)
    out = [parts[0]]
    for k in range(1, len(parts), 2):
        body = parts[k + 1] if k + 1 < len(parts) else ""
        if "```" not in body:
            body = body.rstrip("\n") + "\n```\n"
        out += [parts[k], body]
    return "".join(out)


def parse_tool_calls(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in TOOL_CALL_FENCE_RE.finditer(normalize_tool_fences(text)):
        body = (match.group(1) or "").strip()
        if not body:
            continue
        obj = None
        m = re.search(r"\{[\s\S]*\}", body)
        candidates = [body] + ([m.group(0)] if m else [])
        # Same repair as the extension: regex-style escapes ("a\|b", "\.") are invalid JSON.
        candidates += [repair_json_escapes(c) for c in list(candidates)]
        # Stray `,"` before the closing braces ({…"new_string":"x","}}}) — 3 of 8 lost
        # edits in training cycle 3 ended this way.
        candidates += [_DANGLING_KEY_RE.sub(r'"\1', c) for c in list(candidates)]
        # Stray ")" between the last string and the closing braces (cycle 7, globals-to-di:
        # `…\"dry-run\"\n")}}` — a Python call's paren leaked into the JSON).
        candidates += [_STRAY_PAREN_RE.sub(r'"\1', c) for c in list(candidates) if _STRAY_PAREN_RE.search(c)]
        # Last resort: a bare " inside code (cycle 5, extract-helpers: r\"[\\s-]+", \"-\").
        candidates += [repair_unescaped_quotes(c) for c in list(candidates)]
        # Missing closing braces (cycle 8, split-module: a write ended `…]"}` — 7 rounds lost).
        candidates += [b for b in (balance_braces(c) for c in list(candidates)) if b not in candidates]
        for cand in candidates:
            try:
                # raw_decode takes the first complete object and ignores trailing junk:
                # an extra "}" after a valid call cost 8 edits in training cycle 3.
                obj, _end = _JSON.raw_decode(cand.strip())
                break
            except json.JSONDecodeError:
                continue
        if obj is None:
            out.append({"name": "__malformed__", "arguments": {"raw": body[:400]}})
            continue
        name = str(obj.get("name") or obj.get("tool") or "").strip()
        args = obj.get("arguments", obj.get("args", {})) or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"value": args}
        # "native": true = ChatRouter serialized a native call; that JSON is exact.
        if isinstance(args, dict) and obj.get("native") is not True:
            args = undo_double_escape(name, args)
        key = f"{name}:{json.dumps(args, sort_keys=True)}"
        if name and key not in seen:
            seen.add(key)
            out.append({"name": name, "arguments": args})
    return out


def balance_braces(text: str) -> str:
    """Append the `}` a call is missing, counting braces outside JSON strings only."""
    depth, in_str, i = 0, False, 0
    text = text.rstrip()
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return text + "}" * depth if depth > 0 and not in_str else text


def repair_unescaped_quotes(text: str) -> str:
    """
    Escape a bare `"` inside a JSON string when it cannot be the string's end. A real
    closing quote is followed (after whitespace) by } ] : or by a comma and then the
    next value ("…", {…}, […]). Code in "content"/"old_string" breaks that: in
    `re.sub(r\\"[\\\\s-]+", \\"-\\"` the bare quote is followed by `, \\"`, so it is content.
    Mirrors repairUnescapedQuotes() in the extension's toolProtocol.ts.
    """
    out: list[str] = []
    in_str = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_str and ch == "\\" and i + 1 < n:
            out.append(text[i:i + 2])
            i += 2
            continue
        if ch == '"':
            if not in_str:
                in_str = True
            else:
                j = i + 1
                while j < n and text[j].isspace():
                    j += 1
                closes = j >= n or text[j] in "}]:"
                if not closes and text[j] == ",":
                    j += 1
                    while j < n and text[j].isspace():
                        j += 1
                    closes = j >= n or text[j] in '"{['
                if closes:
                    in_str = False
                else:
                    out.append("\\")
        out.append(ch)
        i += 1
    return "".join(out)


_DOUBLE_ESCAPE_KEYS = ("content", "old_string", "new_string")


def undo_double_escape(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """
    Code strings with no real newline but several literal "\\n" were JSON-escaped twice
    (cycle 7, split-module: after "unescaped quote" errors the coder wrote `\\\\n` and
    `\\\\\\"`, and reports.py became one line of backslashes). Decode them once more.
    Mirrors undoDoubleEscape() in the extension's toolProtocol.ts.
    """
    if name not in {"write_file", "search_replace"}:
        return args
    fixed = dict(args)
    for key in _DOUBLE_ESCAPE_KEYS:
        val = fixed.get(key)
        if not isinstance(val, str) or "\n" in val or val.count("\\n") < 2:
            continue
        try:
            fixed[key] = json.loads(f'"{val}"')
        except json.JSONDecodeError:
            fixed[key] = (val.replace("\\\\", "\x00").replace("\\n", "\n").replace("\\t", "\t")
                          .replace('\\"', '"').replace("\x00", "\\"))
    return fixed


def strip_tool_calls(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", TOOL_CALL_FENCE_RE.sub("", normalize_tool_fences(text))).strip()


# ----------------------------------------------------------------------------- tools
_CD_PREFIX_RE = re.compile(r"^\s*cd\s+(?:/[\w./-]*|~[\w./-]*|\.)\s*(?:&&|;)\s*")
_CMD_TAIL_RE = re.compile(r"(?:\s*(?:2>&1|2>\s*/dev/null|\|\|\s*true))+\s*$")


def normalize_command(command: str) -> str:
    """
    Drop shell habits that mean nothing here: a leading `cd /workspace &&` (commands already
    run in the workspace root; that path does not exist) and a trailing `2>&1` / `|| true`.
    Native cycles 1-2: `cd /workspace && python -m pytest … 2>&1 || true` was refused up to
    12 rounds in a row and three tasks ended at max_rounds with correct edits unverified.
    Mirrors normalizeCommand() in the extension's tools.ts.
    """
    return _CMD_TAIL_RE.sub("", _CD_PREFIX_RE.sub("", (command or "").strip())).strip()


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        # Files whose current content the model has seen: read in an EARLIER round (it had
        # the result in its prompt) or written by itself. Reads from the current round only
        # count once the round ends — a reply that sends read_file and write_file together
        # wrote from a guess (cycle 4: package.json overwritten with invented content).
        self._known: set[Path] = set()
        self._read_this_round: set[Path] = set()

    def end_round(self) -> None:
        self._known |= self._read_this_round
        self._read_this_round.clear()

    def _resolve(self, rel: str) -> Path:
        rel = str(rel or ".").replace("\\", "/").lstrip("/")
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError(f"path escapes workspace: {rel}")
        return path

    def tree(self, limit: int = 200) -> list[str]:
        files = []
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and not (set(p.relative_to(self.root).parts) & SKIP_DIRS):
                files.append(p.relative_to(self.root).as_posix())
        return files[:limit]

    def run(self, name: str, args: dict[str, Any]) -> tuple[bool, str]:
        try:
            handler = getattr(self, f"t_{name}", None)
            if handler is None:
                return False, f"Unknown tool '{name}'. Available: {', '.join(t[0] for t in TOOL_CATALOG)}"
            return handler(args)
        except Exception as exc:  # tool errors are fed back like the extension does
            return False, f"{type(exc).__name__}: {exc}"

    def t___malformed__(self, args):
        return False, (
            "Malformed tool_call JSON — NOT executed, nothing changed. Usually an unescaped \" "
            "inside a string. Redo this edit as a complete-file path fence (```lang path=…) "
            f"instead of JSON. Raw: {str(args.get('raw', ''))[:300]}"
        )

    def t_list_dir(self, args):
        base = self._resolve(args.get("path") or ".")
        if not base.is_dir():
            return False, f"Not a directory: {args.get('path')}"
        rows = []
        for p in sorted(base.iterdir()):
            if p.name in SKIP_DIRS:
                continue
            rows.append(p.name + ("/" if p.is_dir() else ""))
        return True, "\n".join(rows) or "(empty)"

    def t_read_file(self, args):
        path = self._resolve(args.get("path", ""))
        if not path.is_file():
            return False, f"File not found: {args.get('path')}"
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(args.get("startLine") or 1))
        end = min(len(lines), int(args.get("endLine") or len(lines)))
        body = "\n".join(f"{i}| {lines[i - 1]}" for i in range(start, end + 1))
        self._read_this_round.add(path)
        return True, f"{args.get('path')} (lines {start}-{end} of {len(lines)})\n{body}"

    def t_search_text(self, args):
        query = str(args.get("query") or "")
        if not query:
            return False, "query is required"
        base = self._resolve(args.get("path") or ".")
        cap = int(args.get("maxResults") or 50)
        hits = []
        files = [base] if base.is_file() else sorted(base.rglob("*"))
        for p in files:
            if not p.is_file() or set(p.relative_to(self.root).parts) & SKIP_DIRS:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if query.lower() in line.lower():
                    hits.append(f"{p.relative_to(self.root).as_posix()}:{n}: {line.strip()}")
                    if len(hits) >= cap:
                        break
        return True, "\n".join(hits) if hits else "No matches."

    def t_search_replace(self, args):
        path = self._resolve(args.get("path", ""))
        if not path.is_file():
            return False, f"File not found: {args.get('path')}"
        old, new = args.get("old_string"), args.get("new_string")
        if old is None or new is None:
            return False, "old_string and new_string are required"
        text = path.read_text(encoding="utf-8")
        count = text.count(old)
        if count == 0:
            return False, "old_string not found in file (must match exactly, including whitespace; no 'N| ' prefixes)"
        if count > 1 and not args.get("replace_all"):
            return False, f"old_string matches {count} times; add context to make it unique or set replace_all"
        text = text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1)
        path.write_text(text, encoding="utf-8", newline="\n")
        return True, f"Edited {args.get('path')} ({count if args.get('replace_all') else 1} replacement(s))"

    def t_write_file(self, args):
        path = self._resolve(args.get("path", ""))
        content = args.get("content")
        if content is None:
            return False, "content is required"
        existed = path.exists()
        if existed and path not in self._known:
            return False, (
                f"Refused: {args.get('path')} exists and you have not read it yet — NOT written, "
                "nothing changed. Overwriting a file you have not seen replaces real content with "
                "a guess. read_file it this round, then write it next round from what it contains."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8", newline="\n")
        self._known.add(path)
        return True, f"{'Overwrote' if existed else 'Created'} {args.get('path')} ({len(str(content))} chars)"

    def t_delete_file(self, args):
        path = self._resolve(args.get("path", ""))
        if not path.is_file():
            return False, f"File not found: {args.get('path')}"
        path.unlink()
        return True, f"Deleted {args.get('path')}"

    def t_run_command(self, args):
        command = normalize_command(str(args.get("command") or ""))
        if not command:
            return False, "command is required"
        try:
            head = shlex.split(command, posix=False)[0].lower()
        except ValueError:
            head = command.split()[0].lower()
        head = Path(head.strip("\"'")).stem
        # A trailing "2>&1" only merges stderr (already captured); the extension allows it.
        # Quoted text is code, not shell syntax: `python -c "import x; print(x)"` (cycle 7).
        checked = re.sub(r'"[^"]*"|\'[^\']*\'', '""', re.sub(r"\s+2>&1\s*$", "", command))
        if head not in ALLOWED_COMMAND_HEADS or re.search(r"[|&;<>`]|\.\.[\\/]", checked):
            return False, (
                f"Command refused by eval host (allowed: {', '.join(sorted(ALLOWED_COMMAND_HEADS))}; "
                "no pipes/chaining/redirects/parent paths). Commands already run in the workspace "
                "root: send ONE plain command with no cd, e.g. `python -m pytest -q`. Sending this "
                "same command again will be refused again."
            )
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        try:
            proc = subprocess.run(
                command, shell=True, cwd=self.root, capture_output=True, text=True,
                timeout=COMMAND_TIMEOUT_SEC, env=env, encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            return False, f"Timed out after {COMMAND_TIMEOUT_SEC}s: {command}"
        out = (proc.stdout + ("\n" + proc.stderr if proc.stderr.strip() else "")).strip()
        return proc.returncode == 0, f"exit {proc.returncode}\n{out[-MAX_RESULT_CHARS:]}"

    def t_ask_user(self, args):
        return True, (
            "The user is not available during this run. Pick the most reasonable option, "
            "state the assumption in one line, and continue."
        )


# ------------------------------------------------------------------ prompt assembly
NATIVE_PROFILE_RULES = [
    "Rules:",
    "- Prefer RESEARCH tools before writing product files on non-trivial tasks.",
    "- After search_text, read_file with startLine/endLine around hits (avoid whole-file reads).",
    "- Use search_text to discover related files that must change together.",
    "- You may CREATE/EDIT any path in the workspace (not only the open/attached file).",
    "- After tool results appear in [AGENT TOOL TRANSCRIPT], continue or finish — do not invent results.",
    "- Approved plans: EXECUTE all planned files in this turn (every path) → VERIFY → talk to the user in prose.",
    "- Finish by talking to the user in short prose with no tool call (no ### Summary card).",
]


def format_catalog(native: bool | None = None) -> str:
    if native_tools_enabled() if native is None else native:
        return "\n".join([
            "[AVAILABLE TOOLS — profile:full; native function calling]",
            "Call the tools with your native tool-call format. Parameter values are raw text:",
            "write code exactly as it must appear in the file — no JSON, no escaping.",
            "Make one call, then stop; the host tells you when to make the next one.",
            "Several calls can be queued in one turn (e.g. every file you need to read).",
            "",
            *NATIVE_PROFILE_RULES,
            "",
            "Tools: " + ", ".join(n for n, _a, _d in TOOL_CATALOG) + " (parameters are in the tool definitions).",
        ])
    lines = [f"- {n}({a}): {d}" for n, a, d in TOOL_CATALOG]
    return "\n".join([
        "[AVAILABLE TOOLS — profile:full; ChatRouter has no native function-calling; use fences]",
        "To call a tool, emit one or more fences (and nothing that pretends the tool already ran):",
        "",
        "```tool_call",
        '{"name":"search_text","arguments":{"query":"def foo"}}',
        "```",
        "",
        "You may emit several fences in one reply for independent reads — the host can run those in parallel.",
        "",
        *FULL_PROFILE_RULES,
        "",
        "Catalog:",
        *lines,
    ])


def _one_line(e: TranscriptEntry) -> str:
    arg = e.args.get("path") or e.args.get("query") or e.args.get("command") or ""
    first = (e.result.splitlines() or [""])[0][:160]
    return f"R{e.round} {e.name}({arg}) {'ok' if e.ok else 'ERROR'}: {first}"


WORKING_SET_CHARS = 40000
_EDIT_TOOLS = {"search_replace", "write_file", "delete_file", "apply_fence"}
_FULL_WRITE_TOOLS = {"write_file", "apply_fence"}


def working_set_indices(entries: list[TranscriptEntry], budget: int = WORKING_SET_CHARS) -> set[int]:
    """
    Latest successful read_file per path (newest first, within budget). A multi-file
    refactor needs every file it read still in view while it edits; otherwise the coder
    re-reads the same files round after round. Mirrors workingSetIndices() in the extension.
    """
    keep: set[int] = set()
    seen: set[str] = set()
    commands: set[str] = set()
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        if e.name == "run_command":
            # Latest result per command (test output) stays full: it is the evidence
            # for the next fix. Collapsed to "exit 1" the coder just re-runs it.
            cmd = str(e.args.get("command") or "").strip()
            if cmd and cmd not in commands:
                commands.add(cmd)
                keep.add(i)
            continue
        path = str(e.args.get("path") or "")
        if not e.ok or path in seen:
            continue
        if e.name in _FULL_WRITE_TOOLS:
            # A whole-file write IS the file's current content. Without it the coder sees
            # only "Overwrote x (169 chars)" and re-reads every file it just wrote
            # (cycle 5, cjs-to-esm: "I don't actually know what the current file contents are").
            seen.add(path)
            size = len(str(e.args.get("content") or ""))
            if size and size <= budget:
                keep.add(i)
                budget -= size
            continue
        if e.name == "delete_file":
            # The last read of a deleted file is the only copy of its code left (cycle 6,
            # split-module: inventory.py deleted while its replacements failed, then the
            # package was rewritten from memory with renamed fields). Not marking the path
            # as seen keeps the older read in view.
            continue
        if e.name in _EDIT_TOOLS:
            seen.add(path)  # content changed after any earlier read: that read is stale
            continue
        if e.name != "read_file":
            continue
        seen.add(path)
        if len(e.result) <= budget:
            keep.add(i)
            budget -= len(e.result)
    return keep


def _numbered(text: str) -> str:
    return "\n".join(f"{n}| {line}" for n, line in enumerate(text.splitlines(), 1))


def deleted_paths(entries: list[TranscriptEntry]) -> set[str]:
    """Paths whose latest successful edit is a delete (not recreated since)."""
    last: dict[str, str] = {}
    for e in entries:
        if e.ok and e.name in _EDIT_TOOLS:
            last[str(e.args.get("path") or "")] = e.name
    return {p for p, name in last.items() if name == "delete_file"}


def _full_block(e: TranscriptEntry, in_working_set: bool, deleted: set[str] | None = None) -> str:
    args = {k: v for k, v in e.args.items() if k != "content"} if e.name in _FULL_WRITE_TOOLS else e.args
    limit = WORKING_SET_CHARS if e.name == "read_file" else MAX_RESULT_CHARS
    result = e.result if len(e.result) <= limit else e.result[:limit] + "\n…(truncated)"
    if e.name == "read_file" and deleted and str(e.args.get("path") or "") in deleted:
        result = (f"(DELETED since — this is its content from before the delete, the only copy left. "
                  f"Keep every name, field and behavior when you move this code.)\n{result}")
    if e.name in _FULL_WRITE_TOOLS and e.ok and in_working_set:
        result += (f"\nCurrent content of {e.args.get('path')} (exactly what you wrote; "
                   f"no need to read it again):\n{_numbered(str(e.args.get('content') or ''))}")
    return (f"### Round {e.round} — {e.name} ({'ok' if e.ok else 'error'})\n"
            f"Args: {json.dumps(args)[:600]}\nResult:\n{result}")


def format_transcript(entries: list[TranscriptEntry]) -> str:
    if not entries:
        return ""
    full_from = max(0, len(entries) - FULL_TRANSCRIPT_TAIL)
    # Mirror of the extension fix: every result of the latest round stays full, so
    # parallel reads (6 files in one reply) are not collapsed into one-liners.
    last_round = entries[-1].round
    first_of_last = next(i for i, e in enumerate(entries) if e.round == last_round)
    full_from = min(full_from, first_of_last)
    one_from = max(0, full_from - ONE_LINE_MIDDLE)
    working = working_set_indices(entries)
    full = set(range(full_from, len(entries))) | working
    parts = ["[AGENT TOOL TRANSCRIPT — compact]"]
    older = [e for i, e in enumerate(entries[:one_from]) if i not in full]
    if older:
        parts.append("[EARLIER TOOLS — summarized]\n" + "\n".join(f"- {_one_line(e)}" for e in older))
    parts.extend(_one_line(entries[i]) for i in range(one_from, full_from) if i not in full)
    ws = sorted(i for i in full if i < full_from)
    if ws:
        parts.append("[WORKING SET — current content of files you read or wrote + latest result of each command]")
    gone = deleted_paths(entries)
    for i in ws + list(range(full_from, len(entries))):
        parts.append(_full_block(entries[i], i in working, gone))
    return "\n\n".join(parts)


def _has_plan(prose: str) -> bool:
    return bool(re.search(r"^\s*(\*\*)?PLAN\b|^\s*#+\s*Plan\b", prose or "", re.I | re.M))


def build_round_prompt(base: str, entries: list[TranscriptEntry], round_i: int, max_rounds: int,
                       last_prose: str, host_note: str = "") -> str:
    fails = sum(1 for e in entries if not e.ok)
    had_plan = _has_plan(last_prose)
    if not entries:
        block = "\n".join([
            "[AGENT LOOP]",
            f"Round 1/{max_rounds}. Coding turn (may execute).",
            "RESEARCH related files when needed, then a SHORT inline plan and EXECUTE in this turn (search_replace / path fences).",
            "Do NOT stop after PLAN-only. Do NOT emit two PLAN sections. One checklist → edits → short wrap-up.",
            "After search_text, prefer ranged read_file (startLine/endLine) over whole files.",
            "Emit multiple independent read tool_call fences together when useful.",
        ])
    else:
        block = "\n".join(filter(None, [
            "[CONTINUE — agent round]",
            f"Round {round_i + 1}/{max_rounds}. Coding continue.",
            "A PLAN already exists — do NOT rewrite it. EXECUTE remaining steps (all related files), then VERIFY and talk to the user."
            if had_plan else "Either emit more ```tool_call fences, or EXECUTE now, then talk to the user.",
            "Do not stop after one file when more related paths remain.",
            "Never finish silent after edits: end with short prose (what changed).",
            "Do not repeat unchanged prior results. Prefer ranged read_file after search_text.",
            f"{fails} tool failure(s) so far — adapt; do not repeat the same failing call." if fails else "",
        ]))
    status = build_research_status(entries)
    prior = ""
    # Once tests pass after the last edit the green output is the truth; older prose
    # ("npm test failed with an import error…") then misleads (cycle 6, cjs-to-esm
    # rounds 10-14 re-ran green tests because of it).
    if last_prose.strip() and not verified_after_last_edit(entries):
        prior = (
            "[PRIOR ASSISTANT PROSE — do not repeat verbatim"
            + ("; PLAN already present — do not rewrite" if had_plan else "")
            + "]\n" + last_prose.strip()[:600]
        )
    return "\n\n".join(p for p in [base, format_transcript(entries), block, status, prior, host_note] if p)


UNVERIFIED_FINISH_NOTE = (
    "[HOST — not finished yet]\n"
    "You edited files but no test run has passed since your last edit. If the project has "
    "tests, run them now with run_command (e.g. the package.json test script, or "
    "python -m pytest -q). If they fail, fix the cause from the error and run them again. "
    "Only then finish with a short summary."
)


VERIFIED_STOP_NOTE = (
    "[HOST — work is verified]\n"
    "Tests passed after your last edit and the rounds since only re-read, re-searched or "
    "re-ran checks. Those tool calls were NOT run. Reply now with the short summary for the "
    "user (files created / edited / deleted, test result) and NO tool_call fences."
)


def green_idle_rounds(entries: list[TranscriptEntry]) -> int:
    """Rounds after the first passing test that followed the last edit (0 if not verified)."""
    if not verified_after_last_edit(entries):
        return 0
    last_edit = max(i for i, e in enumerate(entries) if e.name in _EDIT_TOOLS and e.ok)
    first_green = next(e.round for e in entries[last_edit + 1:]
                       if e.name == "run_command" and e.ok and _TEST_CMD_RE.search(str(e.args.get("command") or "")))
    return len({e.round for e in entries if e.round > first_green})


FABRICATED_SUMMARY_NOTE = (
    "[HOST — nothing was changed]\n"
    "Your last reply described files as created/edited/deleted and tests as passing, but it "
    "contained NO tool calls and NO path fences, so nothing ran and no file changed. Do the "
    "work now: emit the write_file / search_replace / delete_file tool calls (or path fences), "
    "then run the tests. Do not describe results you have not seen."
)
_CLAIM_RE = re.compile(r"\b(created|edited|updated|deleted|renamed|rewrote|tests? (all )?pass)", re.I)


def claims_unrun_work(prose: str, entries: list[TranscriptEntry]) -> bool:
    """
    A finishing reply claims edits or green tests while no edit ever succeeded (cycle 8,
    globals-to-di round 2: a "### Summary" of six changed files and "All tests pass",
    with zero tool calls).
    """
    # Two or more claims: one stray "updated" in an ordinary answer is not a fabricated summary.
    return (not any(e.name in _EDIT_TOOLS and e.ok for e in entries)
            and len(_CLAIM_RE.findall(prose or "")) >= 2)


def wants_verify_push(entries: list[TranscriptEntry]) -> bool:
    """Edits happened and nothing proved them since (finishing now would be unverified)."""
    return any(e.name in _EDIT_TOOLS and e.ok for e in entries) and not verified_after_last_edit(entries)


_RAW_PATH_RE = re.compile(r'"path"\s*:\s*"([^"]+)"')


def repeated_failure_paths(entries: list[TranscriptEntry]) -> list[str]:
    """Paths whose edit (or malformed edit call) failed at least twice."""
    counts: dict[str, int] = {}
    for e in entries:
        if e.ok or e.name not in _EDIT_TOOLS | {"__malformed__", "tool_call"}:
            continue
        path = str(e.args.get("path") or "")
        if not path:
            m = _RAW_PATH_RE.search(str(e.args.get("raw") or ""))
            path = m.group(1) if m else ""
        if path:
            counts[path] = counts.get(path, 0) + 1
    return [p for p, n in counts.items() if n >= 2]


def repeated_searches(entries: list[TranscriptEntry]) -> tuple[str, str] | None:
    """
    (query, hits) when the latest round re-ran a search_text whose identical query
    already ran with no successful edit in between: the coder is circling, not acting.
    """
    last_round = entries[-1].round
    for i, e in enumerate(entries):
        if e.round != last_round or e.name != "search_text" or not e.ok:
            continue
        q = str(e.args.get("query") or "").lower()
        for j in range(i - 1, -1, -1):
            p = entries[j]
            if p.name in _EDIT_TOOLS and p.ok:
                break
            if (p.name == "search_text" and p.ok and p.round < last_round
                    and str(p.args.get("query") or "").lower() == q):
                # "No matches." repeats are circling too (cycle 6, cjs-to-esm: `require`
                # searched 4 times, always empty); the caller words that case separately.
                return str(e.args.get("query")), "\n".join(p.result.splitlines()[:20])
    return None


_TEST_CMD_RE = re.compile(r"\b(pytest|unittest|node\s+--test|npm\s+(run\s+)?test)\b", re.I)


HOST_TEST_NOTE = ("(The host ran this automatically after your edits. Do not run it again "
                  "until you have edited something.)")


def host_tests_enabled() -> bool:
    """Host runs the project's tests after every round that edited a file (BLOSSOM_EVAL_HOST_TESTS=0 = off)."""
    return os.getenv("BLOSSOM_EVAL_HOST_TESTS", "1").strip().lower() not in {"0", "false", "no", "off"}


def detect_test_command(root: Path) -> str | None:
    """The project's own test command: the package.json test script, else pytest when test files exist."""
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            script = str((json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}).get("test") or "")
        except (json.JSONDecodeError, OSError, AttributeError):
            script = ""
        if script and "no test specified" not in script:
            return "npm test"
    patterns = ("test_*.py", "*_test.py", "tests/test_*.py", "tests/*_test.py", "test/test_*.py")
    if any(next(root.glob(pat), None) for pat in patterns):
        return "python -m pytest -q"
    return None


def host_test_entry(ws: "Workspace", round_entries: list[TranscriptEntry], round_no: int) -> TranscriptEntry | None:
    """
    Run the tests for the coder after a round that changed files, unless it ran them itself.
    A/B 2026-11-20: with edits landing cleanly, runs still failed by finishing or circling
    without a real test result after the last edit; the host can supply that result every time.
    """
    if not any(e.ok and e.name in _EDIT_TOOLS for e in round_entries):
        return None
    if any(e.name == "run_command" and _TEST_CMD_RE.search(str(e.args.get("command") or "")) for e in round_entries):
        return None
    command = detect_test_command(ws.root)
    if not command:
        return None
    ok, res = ws.run("run_command", {"command": command})
    return TranscriptEntry(round_no, "run_command", {"command": command, "by": "host"}, f"{res}\n{HOST_TEST_NOTE}", ok)


def verified_after_last_edit(entries: list[TranscriptEntry]) -> bool:
    """A test command succeeded after the last successful edit (the work is proven)."""
    last_edit = max((i for i, e in enumerate(entries) if e.name in _EDIT_TOOLS and e.ok), default=-1)
    if last_edit < 0:
        return False
    tests = [e for e in entries[last_edit + 1:]
             if e.name == "run_command" and _TEST_CMD_RE.search(str(e.args.get("command") or ""))]
    return bool(tests) and tests[-1].ok


_HIT_RE = re.compile(r"^(?P<path>[^:\n]+):(?P<line>\d+): (?P<text>.+)$")


def edit_templates(hits: str, cap: int = 5) -> list[str]:
    """
    Ready-to-copy search_replace calls for search hits, old_string verbatim from the hit
    (a hit is the stripped line, so it is an exact substring of the file). Cycle 8,
    rename-symbol: it knew the test name had to change but kept writing the line from
    memory (`def test_calc_total_with_tax:` without the parens), failed, and searched
    for 8 rounds instead.
    """
    calls = []
    for raw in hits.splitlines()[:cap]:
        m = _HIT_RE.match(raw.strip())
        if not m:
            continue
        args = {"path": m["path"], "old_string": m["text"], "new_string": "<the corrected line>"}
        calls.append(FENCE_TOOL_CALL + json.dumps({"name": "search_replace", "arguments": args}) + "\n```")
    if not calls:
        return []
    return ["Copy these, keep old_string EXACTLY as given, and replace only the new_string value:", *calls]


FENCE_TOOL_CALL = "```tool_call\n"


def edit_rounds_since_test(entries: list[TranscriptEntry]) -> int:
    """
    Rounds with a successful edit since the last test command ran (cycle 7, globals-to-di:
    after one failing run it rewrote the test file 5 times without ever re-running it).
    """
    last_test = max((i for i, e in enumerate(entries)
                     if e.name == "run_command" and _TEST_CMD_RE.search(str(e.args.get("command") or ""))),
                    default=-1)
    return len({e.round for e in entries[last_test + 1:] if e.ok and e.name in _EDIT_TOOLS})


def searches_since_last_edit(entries: list[TranscriptEntry], cap: int = 12) -> list[str]:
    """Hit lines of the latest search per query run after the last successful edit."""
    last_edit = max((i for i, e in enumerate(entries) if e.name in _EDIT_TOOLS and e.ok), default=-1)
    latest: dict[str, TranscriptEntry] = {}
    for e in entries[last_edit + 1:]:
        if e.name == "search_text" and e.ok:
            latest[str(e.args.get("query") or "")] = e
    lines: list[str] = []
    empty = [q for q, e in latest.items() if e.result.strip() == "No matches."]
    if len(empty) == len(latest):
        return []
    # Cycle 6, rename-symbol: listing only the NEW name's hits hid the decisive
    # `calc_total: No matches` and the coder kept re-checking.
    lines += [f'- search "{q}": No matches (nothing left for it)' for q in empty]
    for query, e in latest.items():
        if query in empty:
            continue
        lines.append(f'- search "{query}":')
        lines += [f"    {h}" for h in e.result.splitlines()[:cap]]
    return lines


def failed_reruns_without_edit(entries: list[TranscriptEntry]) -> tuple[int, str]:
    """
    (count, last output) of failed run_command results since the last successful edit.
    Native cycle 4, rename-symbol: the same failing pytest ran 9 rounds in a row
    (`NameError: name 'calc_total' is not defined`, shopkit\\cart.py:13) with no edit between.
    """
    count, last = 0, ""
    for e in reversed(entries):
        if e.name in _EDIT_TOOLS and e.ok:
            break
        if e.name == "run_command" and not e.ok and e.result.startswith("exit "):
            count += 1
            last = last or e.result
    return count, last


def _error_lines(output: str, cap: int = 6) -> list[str]:
    """The lines of a test run that name the fault: pytest `E ` lines, file:line refs, Error lines."""
    picked = [ln.rstrip() for ln in output.splitlines()
              if re.match(r"\s*(E\s|FAILED\b|\S+\.(?:py|js|mjs|ts):\d+)", ln) or re.search(r"\b\w*Error\b", ln)]
    seen: list[str] = []
    for ln in picked:
        if ln and ln not in seen:
            seen.append(ln[:200])
    return seen[:cap]


def build_research_status(entries: list[TranscriptEntry]) -> str:
    """Mirror of buildResearchStatus() in the extension's toolProtocol.ts."""
    if not entries:
        return ""
    if verified_after_last_edit(entries):
        hits = searches_since_last_edit(entries)
        if hits:
            # Cycle 5, rename-symbol: tests green, the leftover search still hit
            # `def test_calc_total_with_tax`, and "finish if nothing to change" left it
            # re-running the same two searches for 10 rounds without ever acting on the hit.
            return "\n".join([
                "[RESEARCH STATUS — from the host]",
                "Tests pass after your last edit. Your searches since then still find these lines:",
                *hits,
                "Decide NOW, without searching again: if any line above still contains a name, "
                "import or pattern the task asked you to remove or change (also in test names, "
                "comments and docs), fix it with search_replace and re-run the tests. If none do, "
                "FINISH: short summary, NO tool_call fences.",
            ])
        return "\n".join([
            "[RESEARCH STATUS — from the host]",
            "VERIFIED: the tests passed after your last edit. If every planned file is done and "
            "your last leftover search found nothing to change, FINISH NOW: reply with a short "
            "summary (files created / edited / deleted, test result) and NO tool_call fences. "
            "Re-running the same checks will not add anything.",
        ])
    if not working_set_indices(entries) and repeated_failure_paths(entries):
        stuck = repeated_failure_paths(entries)
        return ("[RESEARCH STATUS — from the host]\nThe same edit failed more than once for: "
                + ", ".join(stuck) + ". Send the COMPLETE file(s) in a path fence (```lang path=…) now.")
    reruns, last_output = failed_reruns_without_edit(entries)
    if reruns >= 2:
        return "\n".join([
            "[RESEARCH STATUS — from the host]",
            f"The tests failed {reruns} times in a row and you edited nothing in between. Running "
            "them again will fail the same way. The failure names:",
            *(_error_lines(last_output) or [last_output[-300:]]),
            "Your next reply MUST edit the file and line named above (read_file it first only if "
            "its current content is not shown above), and only then run the tests again.",
        ])
    blind = edit_rounds_since_test(entries)
    if blind >= 3:
        return "\n".join([
            "[RESEARCH STATUS — from the host]",
            f"You have edited files in {blind} rounds since the last test run, without checking "
            "the result. If the project has tests, run them NOW (one run_command) and fix what the error names; do "
            "not edit again before you have seen the test output.",
        ])
    re_searched = repeated_searches(entries)
    if re_searched and re_searched[1].strip() == "No matches.":
        return "\n".join([
            "[RESEARCH STATUS — from the host]",
            f"You already searched {re_searched[0]!r}: No matches, and nothing was edited since. "
            "Nothing is left for that query — do NOT search it again.",
            "Next: run the tests if you have not since your last edit; if they fail, fix the cause "
            "named in the error; if they pass and every planned file is done, FINISH with a short summary.",
        ])
    read_now = [
        str(entries[i].args.get("path")) for i in sorted(working_set_indices(entries))
        if entries[i].name == "read_file" or entries[i].name in _FULL_WRITE_TOOLS
    ]
    read_now = [p for p in read_now if p]
    if not read_now:
        # Native cycle 4: after its edits the reads left the working set, so this returned ""
        # and the same search repeated every round with no status at all.
        if re_searched and not repeated_failure_paths(entries):
            query, hits = re_searched
            return "\n".join([
                "[RESEARCH STATUS — from the host]",
                f"You already searched {query!r} and nothing was edited since. The answer is still:",
                hits,
                "Searching again will not change it. Your next reply MUST edit each line listed above "
                "(search_replace), then search once more and run the tests.",
                *edit_templates(hits),
            ])
        return ""
    edited = any(e.name in _EDIT_TOOLS and e.ok for e in entries)
    last_round = entries[-1].round
    last = [(i, e) for i, e in enumerate(entries) if e.round == last_round]
    reread_only = all(e.name in {"read_file", "list_dir"} for _, e in last)
    def _reread_unchanged(i: int, e: TranscriptEntry) -> bool:
        # A re-read only counts as wasted when nothing edited the file since the last read.
        path = e.args.get("path")
        for p in reversed(entries[:i]):
            if p.args.get("path") != path:
                continue
            if p.name in _FULL_WRITE_TOOLS and p.ok and p.args.get("content"):
                return True  # its own whole-file write is already shown verbatim
            if p.name in _EDIT_TOOLS and p.ok:
                return False
            if p.name == "read_file" and p.ok and p.round < e.round:
                return True
        return False

    repeated = reread_only and any(e.name == "read_file" and _reread_unchanged(i, e) for i, e in last)
    stuck = repeated_failure_paths(entries)
    if re_searched and not stuck:
        query, hits = re_searched
        return "\n".join([
            "[RESEARCH STATUS — from the host]",
            f"Already read, contents unchanged and shown above: {', '.join(read_now)}.",
            f"You already searched {query!r} and nothing was edited since. The answer is still:",
            hits,
            "Searching again will not change it. Your next reply MUST edit each line listed above "
            "(search_replace or a path fence), then search once more and run the tests.",
            *edit_templates(hits),
        ])
    if stuck:
        nxt = ("The same edit failed more than once for: " + ", ".join(stuck) + ". Stop using JSON for it. "
               "Your next reply must contain the COMPLETE new contents of each of those files in a path fence, "
               "e.g. ```js path=" + stuck[0] + " … ```, then a run_command tool_call for the tests.")
    elif repeated:
        nxt = ("You re-read files you already had last round. Research is complete — your next reply "
               "MUST be EXECUTE: write_file / search_replace / delete_file tool_call fences for every planned path.")
    elif edited:
        nxt = "Continue EXECUTE for remaining paths, then search_text for leftovers and run the tests."
    else:
        nxt = "If nothing else is unknown, EXECUTE now (write_file / search_replace / delete_file fences)."
    return "\n".join([
        "[RESEARCH STATUS — from the host]",
        f"Already read, contents unchanged and shown above: {', '.join(read_now)}.",
        "Do NOT read these again. Read only files that are NOT in this list.",
        nxt,
    ])


def build_base_prompt(user_request: str, ws: Workspace) -> str:
    files = ws.tree()
    return "\n\n".join([
        "[USER REQUEST]\n" + user_request.strip(),
        "[REPO KNOWLEDGE]\nWorkspace root: . (all tool paths are relative to it)\nFiles:\n"
        + "\n".join(f"- {f}" for f in files),
        format_catalog(),
    ])


# ------------------------------------------------------------------------ the loop
def _ask(prompt: str, *, timeout_sec: float) -> dict[str, Any]:
    payload = {
        "model": os.getenv("BLOSSOM_EVAL_MODEL", "local-coder"),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "blossom_client": "assistant",
        "blossom_tier": "full",
        "blossom_defer_cloud": True,  # never spend cloud credits from the eval
    }
    if native_tools_enabled():
        payload["tools"] = native_tool_schemas()
    resp = requests.post(chat_router_url(), json=payload,
                         headers={"X-Blossom-Client": "assistant"}, timeout=timeout_sec)
    resp.raise_for_status()
    data = resp.json()
    msg = ((data.get("choices") or [{}])[0].get("message") or {})
    content = msg.get("content") or ""
    if isinstance(content, list):
        content = "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    thoughts = data.get("blossom_thoughts") or []
    reasoning = "".join(
        str(t.get("message") or "") for t in thoughts
        if isinstance(t, dict) and t.get("step") == "model_reasoning"
    ) or str(msg.get("reasoning_content") or "")
    steps = [
        f"{t.get('step')}: {str(t.get('message') or '')[:160]}" for t in thoughts
        if isinstance(t, dict) and t.get("step") not in {"model_reasoning", "coder_draft"}
    ]
    return {"content": str(content), "reasoning": reasoning, "steps": steps,
            "source": data.get("blossom_intel_source") or data.get("model") or ""}


def run_agent(user_request: str, work_dir: Path, *, max_rounds: int = 16,
              timeout_sec: float = float(os.getenv("BLOSSOM_EVAL_ROUND_TIMEOUT", "2400")),
              log_dir: Path | None = None,
              on_round: Callable[[int, str], None] | None = None) -> AgentRunLog:
    ws = Workspace(work_dir)
    base = build_base_prompt(user_request, ws)
    log = AgentRunLog()
    last_prose = ""
    host_note = ""
    verify_pushed = False
    fabrication_pushed = False
    verified_stop_sent = False
    started = time.time()
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)

    for round_i in range(max_rounds):
        prompt = build_round_prompt(base, log.transcript, round_i, max_rounds, last_prose, host_note)
        host_note = ""
        t0 = time.time()
        try:
            reply = _ask(prompt, timeout_sec=timeout_sec)
        except Exception as exc:
            log.stop_reason = f"request failed: {exc}"
            break
        text = reply["content"]
        calls = parse_tool_calls(text)
        prose = strip_tool_calls(text)

        # Path-labeled fences in prose are applied like the extension's Apply step.
        fence_writes = extract_file_writes(prose)
        round_start = len(log.transcript)

        # Verified and idle: tests passed after the last edit and 2+ rounds since only
        # re-checked (cycle 6, globals-to-di: green at round 7, re-read 7 files per round
        # until round 15). Check-only calls are not run; edits still are.
        blocked: list[str] = []
        if (calls and not fence_writes and green_idle_rounds(log.transcript) >= 2
                and not any(c["name"] in _EDIT_TOOLS for c in calls)):
            blocked = [c["name"] for c in calls]
            calls = []
            if not verified_stop_sent:  # first time: ask for the summary; second: end here
                verified_stop_sent = True
                host_note = VERIFIED_STOP_NOTE
        applied = []
        for rel, body in fence_writes.items():
            ok, res = ws.run("write_file", {"path": rel, "content": body})
            log.transcript.append(TranscriptEntry(round_i + 1, "apply_fence", {"path": rel, "content": body}, res, ok))
            if ok:
                applied.append(rel)
                log.edits.append(rel)

        # Deletes run last and only if every edit this round landed: the old file is the
        # source for its replacement (cycle 6, split-module deleted inventory.py while all
        # six replacement writes were malformed).
        calls = [c for c in calls if c["name"] != "delete_file"] + [c for c in calls if c["name"] == "delete_file"]
        for call in calls:
            if call["name"] == "delete_file":
                failed = [e for e in log.transcript[round_start:]
                          if not e.ok and (e.name in _EDIT_TOOLS or e.name == "__malformed__")]
                if failed:
                    res = (f"Not deleted: {len(failed)} edit(s) in this reply failed, and "
                           f"{call['arguments'].get('path')} is the source for them. Fix those edits "
                           "first (path fences for code with quotes), then delete it in a later round.")
                    log.transcript.append(TranscriptEntry(round_i + 1, "delete_file", call["arguments"], res, False))
                    continue
            ok, res = ws.run(call["name"], call["arguments"])
            log.transcript.append(TranscriptEntry(round_i + 1, call["name"], call["arguments"], res, ok))
            if ok and call["name"] in {"search_replace", "write_file", "delete_file"}:
                log.edits.append(str(call["arguments"].get("path")))
        host_test = host_test_entry(ws, log.transcript[round_start:], round_i + 1) if host_tests_enabled() else None
        if host_test:
            log.transcript.append(host_test)
        ws.end_round()

        round_rec = {
            "round": round_i + 1, "sec": round(time.time() - t0, 1), "chars": len(text),
            "tool_calls": [c["name"] for c in calls], "fence_writes": applied,
            "source": reply["source"],
        }
        if blocked:
            round_rec["blocked_check_calls"] = blocked
        if host_test:
            round_rec["host_test"] = "pass" if host_test.ok else "fail"
        log.rounds.append(round_rec)
        if log_dir:
            (log_dir / f"round-{round_i + 1:02d}.prompt.md").write_text(prompt, encoding="utf-8")
            (log_dir / f"round-{round_i + 1:02d}.reply.md").write_text(
                "<!-- router steps -->\n" + "\n".join(reply["steps"]) + "\n<!-- /router steps -->\n\n"
                + (f"<!-- reasoning -->\n{reply['reasoning']}\n<!-- /reasoning -->\n\n" if reply["reasoning"] else "")
                + text, encoding="utf-8")
        if on_round:
            on_round(round_i + 1, f"{round_rec['sec']}s tools={round_rec['tool_calls']} fences={applied}"
                     + (f" blocked={blocked}" if blocked else ""))

        if prose.strip():
            last_prose = prose
        if blocked and host_note == VERIFIED_STOP_NOTE:
            continue  # first verified-idle block: one more round for the summary
        if not calls and host_test and not host_test.ok and round_i + 1 < max_rounds:
            continue  # the failing result is in the transcript; the coder gets a round to fix it
        if not calls:
            if blocked:
                log.final_text = prose
                log.stop_reason = "finished (host: verified, check-only calls ignored)"
                break
            if not fabrication_pushed and claims_unrun_work(prose, log.transcript) and round_i + 1 < max_rounds:
                fabrication_pushed = True
                host_note = FABRICATED_SUMMARY_NOTE
                continue
            # Cycle 5, split-module: finished right after its last write, never ran the tests.
            if not verify_pushed and wants_verify_push(log.transcript) and round_i + 1 < max_rounds:
                verify_pushed = True
                host_note = UNVERIFIED_FINISH_NOTE
                continue
            log.final_text = prose
            log.stop_reason = "finished"
            break
    else:
        log.stop_reason = "max_rounds"

    log.elapsed_sec = round(time.time() - started, 1)
    if log_dir:
        (log_dir / "transcript.json").write_text(json.dumps({
            "rounds": log.rounds,
            "tools": [e.__dict__ for e in log.transcript],
            "final_text": log.final_text,
            "stop_reason": log.stop_reason,
            "elapsed_sec": log.elapsed_sec,
        }, indent=2, default=str), encoding="utf-8")
    return log
