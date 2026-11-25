"""cAST: split code into chunks along its syntax tree (arXiv 2506.15655, EMNLP Findings 2025).

Walk the tree top-down. A node that fits the size budget stays whole; an oversized node is split
into its children recursively; then adjacent small siblings are merged greedily up to the budget.
Size is counted in non-whitespace characters, as in the paper, so indentation does not count.

Why: the store's embedder (all-MiniLM-L6-v2) reads only ~256 tokens per chunk. Crawled GitHub
chunks had a median of 2.9k chars, so most of each chunk was invisible to search.

Fallbacks: no grammar for the language → split at blank lines; Markdown / RST / plain docs →
split at headings, then paragraphs. Every part gets a short stamp (repo/path, enclosing
class/function) so a fragment still says where it came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

# Non-whitespace chars per chunk. MiniLM's wordpiece tokenizer reads code at ~3 chars/token, so
# ~1,000 raw chars (~330 tokens) would still be cut. tune_budget.py on 3,000 rag_github rows +
# 2,000 rag_docs rows (2026-11-25), stamped parts that fit 256 tokens:
#   budget 400: code 97% · 450: code 94%, docs 93% (median ~520 chars) · 500: 89% / 88% · 700: 57%.
# 450 splits a GitHub row into ~5.3 parts on average (the earlier estimate was ~3).
DEFAULT_BUDGET = 450
# A merged group smaller than this is glued onto its neighbour when possible.
MIN_CHUNK_NWS = 60

_WS_RE = re.compile(r"\s+")

# Crawler language label / file extension → tree-sitter-language-pack grammar name.
LANGUAGE_GRAMMAR = {
    "python": "python", "py": "python",
    "javascript": "javascript", "js": "javascript", "jsx": "javascript", "mjs": "javascript", "cjs": "javascript",
    "typescript": "typescript", "ts": "typescript", "tsx": "tsx",
    "php": "php",
    "rust": "rust", "rs": "rust",
    "go": "go",
    "ruby": "ruby", "rb": "ruby",
    "java": "java",
    "csharp": "csharp", "c#": "csharp", "cs": "csharp",
    "sql": "sql",
    "bash": "bash", "shell": "bash", "sh": "bash", "zsh": "bash",
    "c": "c", "h": "c",
    "cpp": "cpp", "c++": "cpp", "cc": "cpp", "cxx": "cpp", "hpp": "cpp", "hh": "cpp", "hxx": "cpp",
    "make": "make", "makefile": "make", "mk": "make",
    "cmake": "cmake",
    "lua": "lua",
    "gdscript": "gdscript", "gd": "gdscript",
    "hlsl": "hlsl", "fx": "hlsl", "fxh": "hlsl",
    "glsl": "glsl", "vert": "glsl", "frag": "glsl", "comp": "glsl", "geom": "glsl",
    "asm": "asm", "s": "asm", "assembly": "asm", "nasm": "nasm",
    "dockerfile": "dockerfile",
    "kotlin": "kotlin", "swift": "swift", "scala": "scala",
    "vue": "vue", "svelte": "svelte", "zig": "zig",
}
DOC_LANGUAGES = {"markdown", "md", "rst", "text", "txt", "documentation", ""}
# Node fields / types that name a scope, for the "in: Class.method" stamp.
_SCOPE_TYPES = re.compile(
    r"(function|method|class|struct|impl|trait|interface|enum|module|namespace|declaration|definition|"
    r"constructor|object|union|macro|label)",
    re.I,
)


def nws_len(text: str) -> int:
    return len(_WS_RE.sub("", text))


@lru_cache(maxsize=None)
def _parser(grammar: str):
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:  # pragma: no cover — tree-sitter missing: line fallback only
        return None
    try:
        return get_parser(grammar)
    except Exception:  # noqa: BLE001 — unknown / undownloadable grammar
        return None


def grammar_for(language: str | None, path: str | None = None) -> str | None:
    lang = (language or "").strip().lower()
    if lang in LANGUAGE_GRAMMAR:
        return LANGUAGE_GRAMMAR[lang]
    name = (path or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name in {"makefile", "gnumakefile"}:
        return "make"
    if name == "dockerfile":
        return "dockerfile"
    if name == "cmakelists.txt":
        return "cmake"
    if "." in name:
        return LANGUAGE_GRAMMAR.get(name.rsplit(".", 1)[-1])
    return None


@dataclass
class Part:
    text: str
    scope: list[str] = field(default_factory=list)


# --- tree walk -----------------------------------------------------------------


def _node_name(node, src: bytes) -> str:
    named = node.child_by_field_name("name")
    if named is None:
        declarator = node.child_by_field_name("declarator")
        while declarator is not None and declarator.child_by_field_name("declarator") is not None:
            declarator = declarator.child_by_field_name("declarator")
        named = declarator
    if named is None:
        return ""
    text = src[named.start_byte : named.end_byte].decode("utf-8", "replace")
    return text.split("(")[0].strip()[:60]


def _split_children(node, src: bytes, budget: int, scope: list[str], out: list[Part]) -> None:
    """Greedy merge of node's children up to the budget; oversized children recurse."""
    name = _node_name(node, src) if _SCOPE_TYPES.search(node.type) else ""
    inner_scope = scope + [name] if name else scope
    group: list = []
    group_size = 0

    def flush() -> None:
        nonlocal group, group_size
        if group:
            text = src[group[0].start_byte : group[-1].end_byte].decode("utf-8", "replace")
            if text.strip():
                out.append(Part(text, list(inner_scope)))
        group = []
        group_size = 0

    for child in node.children:
        text = src[child.start_byte : child.end_byte].decode("utf-8", "replace")
        size = nws_len(text)
        if size > budget:
            flush()
            if child.children:
                _split_children(child, src, budget, inner_scope, out)
            else:
                out.extend(Part(t, list(inner_scope)) for t in _line_split(text, budget))
            continue
        if group and group_size + size > budget:
            flush()
        group.append(child)
        group_size += size
    flush()


def _merge_small(parts: list[Part], budget: int) -> list[Part]:
    """Glue tiny leftovers (a lone `}` or decorator) onto a neighbour that has room."""
    merged: list[Part] = []
    for part in parts:
        size = nws_len(part.text)
        if merged and size < MIN_CHUNK_NWS and nws_len(merged[-1].text) + size <= budget:
            merged[-1] = Part(merged[-1].text.rstrip() + "\n" + part.text.lstrip("\n"), merged[-1].scope)
            continue
        if merged and nws_len(merged[-1].text) < MIN_CHUNK_NWS and nws_len(merged[-1].text) + size <= budget:
            merged[-1] = Part(merged[-1].text.rstrip() + "\n" + part.text.lstrip("\n"), part.scope)
            continue
        merged.append(part)
    return merged


def cast_split(code: str, grammar: str, budget: int = DEFAULT_BUDGET) -> list[Part] | None:
    """cAST parts, or None when there is no parser for the grammar."""
    parser = _parser(grammar)
    if parser is None:
        return None
    src = code.encode("utf-8")
    if nws_len(code) <= budget:
        return [Part(code)]
    tree = parser.parse(src)
    out: list[Part] = []
    _split_children(tree.root_node, src, budget, [], out)
    if not out:
        return None
    return _merge_small(out, budget)


# --- fallbacks -----------------------------------------------------------------


def _hard_split(text: str, budget: int) -> list[str]:
    """Last resort for one huge line (minified code, a table row): cut by characters."""
    out, cur = [], []
    size = 0
    for ch in text:
        cur.append(ch)
        if not ch.isspace():
            size += 1
        if size >= budget:
            out.append("".join(cur))
            cur, size = [], 0
    if "".join(cur).strip():
        out.append("".join(cur))
    return out


def _greedy(pieces: list[str], budget: int, joiner: str) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    size = 0
    for piece in pieces:
        n = nws_len(piece)
        if n > budget:
            if cur:
                out.append(joiner.join(cur))
                cur, size = [], 0
            out.extend(_hard_split(piece, budget))
            continue
        if cur and size + n > budget:
            out.append(joiner.join(cur))
            cur, size = [], 0
        cur.append(piece)
        size += n
    if cur:
        out.append(joiner.join(cur))
    return [o for o in out if o.strip()]


def _line_split(text: str, budget: int) -> list[str]:
    """Blank-line blocks merged to the budget; oversized blocks split by lines."""
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    pieces: list[str] = []
    for block in blocks:
        if nws_len(block) <= budget:
            pieces.append(block)
        else:
            pieces.extend(_greedy(block.split("\n"), budget, "\n"))
    return _greedy(pieces, budget, "\n\n")


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$|^(.+)\n(=+|-+)\s*$", re.M)


def doc_split(text: str, budget: int = DEFAULT_BUDGET) -> list[Part]:
    """Markdown/RST/prose: sections at headings (heading path kept as scope), then paragraphs."""
    if nws_len(text) <= budget:
        return [Part(text)]
    sections: list[tuple[list[str], str]] = []
    path: list[tuple[int, str]] = []
    last = 0
    current_scope: list[str] = []
    for m in _HEADING_RE.finditer(text):
        body = text[last : m.start()]
        if body.strip():
            sections.append((current_scope, body))
        if m.group(1):
            level, title = len(m.group(1)), m.group(2)
        else:
            level, title = (1 if m.group(4).startswith("=") else 2), m.group(3)
        path = [p for p in path if p[0] < level] + [(level, title.strip()[:80])]
        current_scope = [t for _, t in path]
        last = m.start()
    tail = text[last:]
    if tail.strip():
        sections.append((current_scope, tail))
    out: list[Part] = []
    for scope, body in sections:
        for piece in _line_split(body, budget):
            out.append(Part(piece, list(scope)))
    return _merge_small(out, budget)


# --- public entry --------------------------------------------------------------

_GITHUB_HEADER_RE = re.compile(r"\A(?:# [^\n]*\n)+\n")


def strip_crawl_header(text: str) -> str:
    """Drop the crawler's '# repo — path / # language / # url / # about' block."""
    m = _GITHUB_HEADER_RE.match(text)
    if m and re.search(r"^# (?:language|url):", m.group(0), re.M):
        return text[m.end() :]
    return text


def stamp(part: Part, *, where: str, language: str = "") -> str:
    head = f"// {where}" if where else ""
    if part.scope:
        head += f" · in {'.'.join(s for s in part.scope if s)}"
    if language:
        head += f" · {language}"
    return f"{head.strip()}\n{part.text.strip()}" if head.strip() else part.text.strip()


def chunk_text(
    text: str,
    *,
    language: str | None = None,
    path: str | None = None,
    kind: str = "code_sample",
    budget: int = DEFAULT_BUDGET,
) -> tuple[list[Part], str]:
    """Split one crawled row's text. Returns (parts, method) — method is cast / lines / doc."""
    body = strip_crawl_header(text)
    lang = (language or "").strip().lower()
    is_doc = kind == "documentation" or (lang in DOC_LANGUAGES and not grammar_for(None, path))
    if is_doc or (path or "").lower().endswith((".md", ".rst", ".txt", ".markdown")):
        return doc_split(body, budget), "doc"
    grammar = grammar_for(lang, path)
    if grammar:
        parts = cast_split(body, grammar, budget)
        if parts is not None:
            return parts, "cast"
    return [Part(t) for t in _line_split(body, budget)], "lines"
