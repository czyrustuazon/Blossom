"""Route user queries to the Code Execution Agent vs other ChatRouter paths."""

from __future__ import annotations

import re
from typing import Literal

RouteKind = Literal["agent", "coding", "japanese", "casual"]

# Tasks that benefit from the Python REPL + agent_utils (not IDE fence editing).
AGENT_KEYWORDS: tuple[str, ...] = (
    "analyze csv",
    "analyze data",
    "dataframe",
    "pandas",
    "numpy",
    "scipy",
    "sympy",
    "plot ",
    "matplotlib",
    "seaborn",
    "excel",
    "spreadsheet",
    "xlsx",
    "workbook",
    "pdf",
    "merge pdf",
    "extract text from pdf",
    "extract tables",
    "git diff",
    "git commit",
    "commit and push",
    "stage changes",
    "run python",
    "execute python",
    "python repl",
    "calculate ",
    "compute ",
    "statistics",
    "linear program",
    "optimize ",
    "regression",
    "correlation",
    "merge pdfs",
    "opencv",
    "playwright scrape",
    "web scrape",
)

# Strong signals even without keywords.
AGENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(run|execute|eval)\b.*\bpython\b", re.I),
    re.compile(r"\b(import|using)\s+pandas\b", re.I),
    re.compile(r"\b(sympy|scipy|matplotlib)\b", re.I),
    re.compile(r"\b(xlsx|\.csv|\.pdf)\b", re.I),
    re.compile(r"\bgit\s+(status|diff|commit|push)\b", re.I),
    re.compile(r"\bmerge\s+(these\s+)?pdfs?\b", re.I),
)

CODING_OVERRIDE_KEYWORDS: tuple[str, ...] = (
    "write_file",
    "read_file",
    "list_dir",
    "tool_call",
    "path=",
    "create file",
    "edit file",
    "refactor",
    "fix bug",
    "implement ",
    "vscode",
    "extension",
    "typescript",
    "javascript",
    "react",
    "html",
    "css",
)


def is_agent_execution_request(
    user_prompt: str,
    *,
    looks_like_editor_dump: bool = False,
) -> bool:
    """True when the query should use the sandboxed Python agent layer."""
    text = (user_prompt or "").strip()
    if not text:
        return False

    lower = text.lower()

    # Blossom Assistant tool/agent loops stay on the coding route.
    if looks_like_editor_dump or "```tool_call" in text:
        return False
    if any(kw in lower for kw in CODING_OVERRIDE_KEYWORDS):
        return False

    if any(p.search(text) for p in AGENT_PATTERNS):
        return True
    return any(kw in lower for kw in AGENT_KEYWORDS)


def classify_route(
    user_prompt: str,
    *,
    looks_like_editor_dump: bool = False,
    is_coding_fn,
    is_japanese_fn,
) -> RouteKind:
    """Pick agent vs coding vs japanese vs casual for ChatRouter."""
    if is_agent_execution_request(
        user_prompt, looks_like_editor_dump=looks_like_editor_dump
    ):
        return "agent"
    if is_coding_fn(user_prompt):
        return "coding"
    if is_japanese_fn(user_prompt):
        return "japanese"
    return "casual"
