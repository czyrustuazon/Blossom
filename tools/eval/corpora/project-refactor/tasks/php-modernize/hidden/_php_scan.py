"""
Minimal PHP lexer for static acceptance checks (php is not installed on the eval host).

Splits a file into html / code / string / comment tokens so checks can look at code only,
find SQL string literals and what is concatenated onto them, and verify bracket balance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

OPEN_TAG_RE = re.compile(r"<\?(?:php\b|=)?", re.IGNORECASE)
HEREDOC_RE = re.compile(r"<<<[ \t]*(['\"]?)([A-Za-z_]\w*)\1\r?\n")


@dataclass
class Tok:
    kind: str  # html | code | sq | dq | comment
    text: str


class ScanError(ValueError):
    pass


def tokenize(src: str) -> list[Tok]:
    toks: list[Tok] = []
    i, n = 0, len(src)
    code = []

    def flush() -> None:
        if code:
            toks.append(Tok("code", "".join(code)))
            code.clear()

    while i < n:
        # HTML mode until an open tag.
        m = OPEN_TAG_RE.search(src, i)
        if not m:
            toks.append(Tok("html", src[i:]))
            break
        if m.start() > i:
            toks.append(Tok("html", src[i:m.start()]))
        i = m.end()
        # PHP mode until ?> (outside strings/comments).
        while i < n:
            c = src[i]
            two = src[i:i + 2]
            if two == "?>":
                flush()
                i += 2
                break
            if two == "//" or (c == "#" and src[i + 1:i + 2] != "["):
                flush()
                j = i
                while j < n and src[j] != "\n" and src[j:j + 2] != "?>":
                    j += 1
                toks.append(Tok("comment", src[i:j]))
                i = j
                continue
            if two == "/*":
                flush()
                j = src.find("*/", i + 2)
                if j < 0:
                    raise ScanError("unterminated /* comment")
                toks.append(Tok("comment", src[i:j + 2]))
                i = j + 2
                continue
            if c in "'\"":
                flush()
                j = i + 1
                while j < n and src[j] != c:
                    j += 2 if src[j] == "\\" else 1
                if j >= n:
                    raise ScanError(f"unterminated {c} string starting {src[i:i + 40]!r}")
                toks.append(Tok("sq" if c == "'" else "dq", src[i:j + 1]))
                i = j + 1
                continue
            hd = HEREDOC_RE.match(src, i)
            if hd:
                flush()
                end_re = re.compile(r"^[ \t]*" + re.escape(hd.group(2)) + r"\b", re.MULTILINE)
                e = end_re.search(src, hd.end())
                if not e:
                    raise ScanError("unterminated heredoc")
                body = src[hd.end():e.start()]
                kind = "sq" if hd.group(1) == "'" else "dq"
                toks.append(Tok(kind, ('"' if kind == "dq" else "'") + body + ('"' if kind == "dq" else "'")))
                i = e.end()
                continue
            code.append(c)
            i += 1
        flush()
    return toks


def code_only(src: str) -> str:
    """Code with comments dropped and every string literal replaced by ''."""
    out = []
    for t in tokenize(src):
        if t.kind == "code":
            out.append(t.text)
        elif t.kind in ("sq", "dq"):
            out.append("''")
        elif t.kind == "comment":
            out.append(" ")
    return "".join(out)


def balance_errors(src: str) -> list[str]:
    try:
        toks = tokenize(src)
    except ScanError as exc:
        return [str(exc)]
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    errs: list[str] = []
    for t in toks:
        if t.kind != "code":
            continue
        for ch in t.text:
            if ch in "([{":
                stack.append(ch)
            elif ch in pairs:
                if not stack or stack[-1] != pairs[ch]:
                    errs.append(f"unexpected {ch!r}")
                    return errs
                stack.pop()
    if stack:
        errs.append(f"unclosed {''.join(stack)!r}")
    return errs


SQL_START_RE = re.compile(r"^\s*(select|insert|update|delete|replace)\b", re.IGNORECASE)
SQL_ANY_RE = re.compile(r"\b(select\s.+\sfrom|insert\s+into|update\s+\w+\s+set|delete\s+from|\swhere\s)", re.IGNORECASE | re.DOTALL)
INTERP_RE = re.compile(r"(?<!\\)\$(?:[A-Za-z_{])|\{\$")
SAFE_OPERAND_RE = re.compile(
    r"^\s*(?:\(int\)\s*\$\w+|intval\(\s*\$\w+\s*\)|[A-Z_][A-Z0-9_]*|\d+)\s*$"
)


def unsafe_sql(src: str) -> list[str]:
    """
    SQL literals that splice in variables: a double-quoted SQL string with $interpolation,
    or a SQL literal with `. $var` concatenated onto it (int casts and CONSTANTS are fine).
    """
    # Stream of code with each string literal replaced by a marker \x00<index>\x01.
    toks = tokenize(src)
    parts: list[str] = []
    bodies: dict[int, tuple[str, str]] = {}
    for idx, t in enumerate(toks):
        if t.kind == "code":
            parts.append(t.text)
        elif t.kind in ("sq", "dq"):
            bodies[idx] = (t.kind, t.text[1:-1])
            parts.append(f"\x00{idx}\x01")
        elif t.kind == "comment":
            parts.append(" ")
        else:
            parts.append(";")  # html ends a statement
    stream = "".join(parts)

    def operands(text: str) -> list[str]:
        """Split one concatenation chain (already stripped of the leading '.') into operands."""
        ops, depth, cur = [], 0, []
        for ch in text:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and ch in ",;?:":
                break
            elif depth == 0 and ch == "=" :
                break
            if depth == 0 and ch == ".":
                ops.append("".join(cur))
                cur = []
                continue
            cur.append(ch)
        ops.append("".join(cur))
        return [o.strip() for o in ops if o.strip()]

    problems: list[str] = []
    for m in re.finditer(r"\x00(\d+)\x01", stream):
        kind, body = bodies[int(m.group(1))]
        if not (SQL_START_RE.match(body) or SQL_ANY_RE.search(body)):
            continue
        if kind == "dq" and INTERP_RE.search(body):
            problems.append(f"interpolated SQL: {body.strip()[:80]!r}")
            continue
        after = stream[m.end():]
        before = stream[:m.start()]
        bad = ""
        fwd = re.match(r"\s*\.(?!=)", after)
        if fwd:
            for op in operands(after[fwd.end():]):
                plain = re.sub(r"\x00\d+\x01", "", op)
                if "$" in plain and not SAFE_OPERAND_RE.match(plain):
                    bad = plain
                    break
        if not bad:
            # `$var . "SQL…"` / `$row['x'] . "…"` directly before the literal.
            back = re.search(r"(\$\w+(?:\[[^\]]*\]|->\w+)*)\s*\.\s*$", before)
            if back and not re.search(r"(?:\(int\)\s*|intval\(\s*)\$\w+\s*\)?\s*\.\s*$", before):
                bad = back.group(1)
        if bad:
            problems.append(f"variable concatenated into SQL: {body.strip()[:60]!r} . {bad.strip()[:30]}")
    return problems


def sql_literals(src: str) -> list[str]:
    out = []
    for t in tokenize(src):
        if t.kind in ("sq", "dq"):
            body = t.text[1:-1]
            if SQL_START_RE.match(body) or SQL_ANY_RE.search(body):
                out.append(body)
    return out


def php_files(root: Path) -> list[Path]:
    skip = {"_acceptance", "tests", ".git", "vendor"}
    return sorted(p for p in root.rglob("*.php") if not (set(p.relative_to(root).parts) & skip))
