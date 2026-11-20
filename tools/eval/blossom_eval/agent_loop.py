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
     "Run a shell command in the workspace root (tests, python/node probes, git). Returns exit code + output."),
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
def parse_tool_calls(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in TOOL_CALL_FENCE_RE.finditer(text or ""):
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
        key = f"{name}:{json.dumps(args, sort_keys=True)}"
        if name and key not in seen:
            seen.add(key)
            out.append({"name": name, "arguments": args})
    return out


def strip_tool_calls(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", TOOL_CALL_FENCE_RE.sub("", text or "")).strip()


# ----------------------------------------------------------------------------- tools
class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()

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
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        path.write_text(str(content), encoding="utf-8", newline="\n")
        return True, f"{'Overwrote' if existed else 'Created'} {args.get('path')} ({len(str(content))} chars)"

    def t_delete_file(self, args):
        path = self._resolve(args.get("path", ""))
        if not path.is_file():
            return False, f"File not found: {args.get('path')}"
        path.unlink()
        return True, f"Deleted {args.get('path')}"

    def t_run_command(self, args):
        command = str(args.get("command") or "").strip()
        if not command:
            return False, "command is required"
        try:
            head = shlex.split(command, posix=False)[0].lower()
        except ValueError:
            head = command.split()[0].lower()
        head = Path(head.strip("\"'")).stem
        if head not in ALLOWED_COMMAND_HEADS or re.search(r"[|&;<>`]|\.\.[\\/]", command):
            return False, (
                f"Command refused by eval host (allowed: {', '.join(sorted(ALLOWED_COMMAND_HEADS))}; "
                "no pipes/chaining/redirects/parent paths)."
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
def format_catalog() -> str:
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
        if e.name in _EDIT_TOOLS and e.ok:
            seen.add(path)  # content changed after any earlier read: that read is stale
            continue
        if e.name != "read_file" or not e.ok or path in seen:
            continue
        seen.add(path)
        if len(e.result) <= budget:
            keep.add(i)
            budget -= len(e.result)
    return keep


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
    full = set(range(full_from, len(entries))) | working_set_indices(entries)
    parts = ["[AGENT TOOL TRANSCRIPT — compact]"]
    older = [e for i, e in enumerate(entries[:one_from]) if i not in full]
    if older:
        parts.append("[EARLIER TOOLS — summarized]\n" + "\n".join(f"- {_one_line(e)}" for e in older))
    parts.extend(_one_line(entries[i]) for i in range(one_from, full_from) if i not in full)
    ws = sorted(i for i in full if i < full_from)
    if ws:
        parts.append("[WORKING SET — files you read (unchanged since) + latest result of each command]")
    for i in ws + list(range(full_from, len(entries))):
        e = entries[i]
        limit = WORKING_SET_CHARS if e.name == "read_file" else MAX_RESULT_CHARS
        result = e.result if len(e.result) <= limit else e.result[:limit] + "\n…(truncated)"
        parts.append(
            f"### Round {e.round} — {e.name} ({'ok' if e.ok else 'error'})\n"
            f"Args: {json.dumps(e.args)[:600]}\nResult:\n{result}"
        )
    return "\n\n".join(parts)


def _has_plan(prose: str) -> bool:
    return bool(re.search(r"^\s*(\*\*)?PLAN\b|^\s*#+\s*Plan\b", prose or "", re.I | re.M))


def build_round_prompt(base: str, entries: list[TranscriptEntry], round_i: int, max_rounds: int,
                       last_prose: str) -> str:
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
    if last_prose.strip():
        prior = (
            "[PRIOR ASSISTANT PROSE — do not repeat verbatim"
            + ("; PLAN already present — do not rewrite" if had_plan else "")
            + "]\n" + last_prose.strip()[:600]
        )
    return "\n\n".join(p for p in [base, format_transcript(entries), block, status, prior] if p)


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
                if p.result.strip() == "No matches.":
                    break
                return str(e.args.get("query")), "\n".join(p.result.splitlines()[:20])
    return None


_TEST_CMD_RE = re.compile(r"\b(pytest|unittest|node\s+--test|npm\s+(run\s+)?test)\b", re.I)


def verified_after_last_edit(entries: list[TranscriptEntry]) -> bool:
    """A test command succeeded after the last successful edit (the work is proven)."""
    last_edit = max((i for i, e in enumerate(entries) if e.name in _EDIT_TOOLS and e.ok), default=-1)
    if last_edit < 0:
        return False
    tests = [e for e in entries[last_edit + 1:]
             if e.name == "run_command" and _TEST_CMD_RE.search(str(e.args.get("command") or ""))]
    return bool(tests) and tests[-1].ok


def build_research_status(entries: list[TranscriptEntry]) -> str:
    """Mirror of buildResearchStatus() in the extension's toolProtocol.ts."""
    if not entries:
        return ""
    if verified_after_last_edit(entries):
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
    read_now = [
        str(entries[i].args.get("path")) for i in sorted(working_set_indices(entries))
        if entries[i].name == "read_file"
    ]
    read_now = [p for p in read_now if p]
    if not read_now:
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
            if p.name in _EDIT_TOOLS and p.ok:
                return False
            if p.name == "read_file" and p.ok and p.round < e.round:
                return True
        return False

    repeated = reread_only and any(e.name == "read_file" and _reread_unchanged(i, e) for i, e in last)
    stuck = repeated_failure_paths(entries)
    re_searched = repeated_searches(entries)
    if re_searched and not stuck:
        query, hits = re_searched
        return "\n".join([
            "[RESEARCH STATUS — from the host]",
            f"Already read, contents unchanged and shown above: {', '.join(read_now)}.",
            f"You already searched {query!r} and nothing was edited since. The answer is still:",
            hits,
            "Searching again will not change it. Your next reply MUST edit each line listed above "
            "(search_replace or a path fence), then search once more and run the tests.",
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
    started = time.time()
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)

    for round_i in range(max_rounds):
        prompt = build_round_prompt(base, log.transcript, round_i, max_rounds, last_prose)
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
        applied = []
        for rel, body in fence_writes.items():
            ok, res = ws.run("write_file", {"path": rel, "content": body})
            log.transcript.append(TranscriptEntry(round_i + 1, "apply_fence", {"path": rel}, res, ok))
            if ok:
                applied.append(rel)
                log.edits.append(rel)

        for call in calls:
            ok, res = ws.run(call["name"], call["arguments"])
            log.transcript.append(TranscriptEntry(round_i + 1, call["name"], call["arguments"], res, ok))
            if ok and call["name"] in {"search_replace", "write_file", "delete_file"}:
                log.edits.append(str(call["arguments"].get("path")))

        round_rec = {
            "round": round_i + 1, "sec": round(time.time() - t0, 1), "chars": len(text),
            "tool_calls": [c["name"] for c in calls], "fence_writes": applied,
            "source": reply["source"],
        }
        log.rounds.append(round_rec)
        if log_dir:
            (log_dir / f"round-{round_i + 1:02d}.prompt.md").write_text(prompt, encoding="utf-8")
            (log_dir / f"round-{round_i + 1:02d}.reply.md").write_text(
                "<!-- router steps -->\n" + "\n".join(reply["steps"]) + "\n<!-- /router steps -->\n\n"
                + (f"<!-- reasoning -->\n{reply['reasoning']}\n<!-- /reasoning -->\n\n" if reply["reasoning"] else "")
                + text, encoding="utf-8")
        if on_round:
            on_round(round_i + 1, f"{round_rec['sec']}s tools={round_rec['tool_calls']} fences={applied}")

        if prose.strip():
            last_prose = prose
        if not calls:
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
