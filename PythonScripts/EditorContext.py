"""
Pack huge Blossom/VS Code editor dumps into a coder-sized prompt.

Strategy (select → chunk → rank → pack):
  1. Parse <<<FILE path="...">>> … <<<END_FILE>>> blocks
  2. Keep the short [USER REQUEST]
  3. Prefer files named/mentioned in the ask; drop unrelated open tabs
  4. Split oversized files into overlapping line chunks
  5. Rank chunks by keyword overlap with the ask
  6. Pack highest-scoring pieces until the token budget is full
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable

# Rough chars-per-token; matches ChatRouter budgeting.
_CHARS_PER_TOKEN = 4

EDITOR_PACK_ENABLED = os.getenv("EDITOR_CONTEXT_PACK", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Leave room for system prompt, lessons, web, agent protocol, and the model reply.
_CODER_REPLY_RESERVE = max(1024, int(os.getenv("CODER_REPLY_RESERVE", "4096")))
_CODER_PROMPT_OVERHEAD = max(1024, int(os.getenv("CODER_PROMPT_OVERHEAD", "6144")))
EDITOR_TOKEN_BUDGET = max(
    2048,
    int(os.getenv("EDITOR_CONTEXT_BUDGET", "0"))
    or (
        int(os.getenv("CODER_CTX_SIZE", "32768"))
        - _CODER_REPLY_RESERVE
        - _CODER_PROMPT_OVERHEAD
    ),
)
EDITOR_MAX_FILES = max(1, int(os.getenv("EDITOR_MAX_FILES", "6")))
EDITOR_CHUNK_LINES = max(40, int(os.getenv("EDITOR_CHUNK_LINES", "160")))
EDITOR_CHUNK_OVERLAP = max(0, int(os.getenv("EDITOR_CHUNK_OVERLAP", "20")))
EDITOR_REPO_KNOWLEDGE_CHARS = max(0, int(os.getenv("EDITOR_REPO_KNOWLEDGE_CHARS", "800")))
EDITOR_SEQUENTIAL_PREVIEW_CHARS = max(
    40, int(os.getenv("EDITOR_SEQUENTIAL_PREVIEW_CHARS", "140"))
)

SEQUENTIAL_CODER_PROMPT = (
    "You are Blossom's coding agent. Full editor files did not fit the model context.\n"
    "Use read_file with startLine/endLine from [CHUNK CATALOG] to fetch excerpts before editing.\n"
    "Workflow: (1) ```tool_call read_file for needed chunk(s), (2) then path-labeled file fences.\n"
    "One fence per file. Preserve existing content on edits unless a full rewrite was requested."
)

_FILE_BLOCK_RE = re.compile(
    r"<<<FILE\s+path=(?P<q>[\"']?)(?P<path>.*?)(?P=q)\s*>>>\r?\n"
    r"(?P<body>.*?)\r?\n"
    r"<<<END_FILE>>>",
    re.DOTALL | re.IGNORECASE,
)

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_./\\-]+")
# Common "create this file" name mentions in free text.
_FILENAME_RE = re.compile(
    r"""(?ix)
    (?:
      (?:create|make|add|generate|new|write)\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?(?:file\s+(?:called|named)\s+)?
      |
      (?:file\s+(?:called|named)\s+)
    )
    [`'"]?([a-zA-Z0-9_.\-]+\.[a-zA-Z0-9]+)[`'"]?
    |
    [`'"]([a-zA-Z0-9_.\-]+\.[a-zA-Z0-9]+)[`'"]
    \s+(?:file|page)
    """
)
_BARE_FILE_RE = re.compile(
    r"""(?ix)\b([a-zA-Z0-9_.\-]+\.(?:html?|css|js|ts|tsx|jsx|py|json|md|txt))\b"""
)


def mentioned_filenames(ask: str) -> list[str]:
    found: list[str] = []
    for match in _FILENAME_RE.finditer(ask or ""):
        name = match.group(1) or match.group(2)
        if name:
            found.append(name)
    for match in _BARE_FILE_RE.finditer(ask or ""):
        found.append(match.group(1))
    # stable unique, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for name in found:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


def build_task_brief(ask: str, attached_paths: Iterable[str]) -> str:
    """
    Explicit plan for weaker local models: create vs edit, multi-file output rules.
    """
    ask_l = (ask or "").lower()
    attached = {p.replace("\\", "/").rsplit("/", 1)[-1].lower() for p in attached_paths}
    attached_full = [p.replace("\\", "/") for p in attached_paths]
    mentioned = mentioned_filenames(ask)

    create_names: list[str] = []
    edit_names: list[str] = []
    for name in mentioned:
        if name.lower() in attached:
            edit_names.append(name)
        else:
            # "about.html" when only index.html is attached → create
            create_names.append(name)

    create_words = any(
        w in ask_l
        for w in (
            "create",
            "generate",
            "make a new",
            "new file",
            "add a file",
            "write a file",
        )
    )
    keep_words = any(
        w in ask_l
        for w in (
            "keep the original",
            "keep original",
            "don't replace",
            "do not replace",
            "don't overwrite",
            "do not overwrite",
            "preserve",
        )
    )

    lines = [
        "[TASK BRIEF — follow exactly]",
        f"- User ask: {ask.strip()[:500]}",
    ]
    if attached_full:
        lines.append("- Attached open files: " + ", ".join(attached_full[:8]))
    if create_names or create_words:
        targets = ", ".join(dict.fromkeys(create_names)) or "(new file named in the ask)"
        lines.append(
            f"- CREATE new file(s): {targets}. These must be NEW paths — "
            "do NOT put their contents into an existing attached file."
        )
    if edit_names or (attached_full and not create_names):
        targets = ", ".join(dict.fromkeys(edit_names)) if edit_names else ", ".join(attached_full[:4])
        lines.append(
            f"- EDIT existing file(s) minimally: {targets}. "
            "Preserve all unrelated original content; only apply the requested change "
            "(e.g. add a link). Never replace a whole page with a stub unless asked."
        )
    if keep_words or (create_names and edit_names):
        lines.append(
            "- Preserve originals: keep existing markup/structure; additive edits only."
        )
    lines.extend(
        [
            "- Output format: one markdown fence PER file, with a path hint in the info string "
            "when possible, e.g. ```html path=about.html or ```html about.html",
            "- If creating AND editing, output BOTH files in the same reply "
            "(edited index.html + new about.html).",
            "- Never overwrite index.html (or any attached file) with the contents of a "
            "different new file the user asked to create.",
        ]
    )
    return "\n".join(lines)


@dataclass
class EditorFile:
    path: str
    body: str

    @property
    def name(self) -> str:
        return self.path.replace("\\", "/").rsplit("/", 1)[-1]


@dataclass
class FileChunk:
    path: str
    start_line: int
    end_line: int
    text: str
    score: float = 0.0


def approx_tokens(text: str) -> int:
    return max(1, (len(text or "") + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def looks_like_editor_dump(user_prompt: str) -> bool:
    text = user_prompt or ""
    return "<<<FILE" in text or "[EDITOR CONTEXT]" in text.upper()


def extract_user_request(user_prompt: str) -> str:
    text = user_prompt or ""
    marker = "[USER REQUEST]"
    if marker in text:
        tail = text.split(marker, 1)[1].strip()
        for stop in (
            "[REPO KNOWLEDGE",
            "[EDITOR CONTEXT",
            "[AGENT TOOL",
            "[CONTINUE",
            "[AGENT LOOP",
            "[AVAILABLE TOOLS",
            "[CODING AGENT PROTOCOL",
            "<<<FILE",
        ):
            if stop.startswith("<<<"):
                idx = tail.find(stop)
            else:
                idx = tail.upper().find(stop.upper())
            if idx >= 0:
                tail = tail[:idx].strip()
        if tail:
            return tail[:2000]

    if looks_like_editor_dump(text):
        head = text.split("<<<FILE", 1)[0]
        head = re.split(r"\[EDITOR CONTEXT\]", head, maxsplit=1, flags=re.I)[0].strip()
        lines = [ln.strip() for ln in head.splitlines() if ln.strip()]
        skip_prefixes = (
            "the user already has",
            "fix or discuss",
            "when you fix",
            "prefer a full-file",
            "do not ask",
            "do not ask them",
        )
        useful = [
            ln
            for ln in lines
            if not any(ln.lower().startswith(p) for p in skip_prefixes)
        ]
        if useful:
            return "\n".join(useful)[-1500:]
        return head[:800] if head else text[:800]

    return text.strip()[:2000]


def parse_editor_files(user_prompt: str) -> list[EditorFile]:
    files: list[EditorFile] = []
    for match in _FILE_BLOCK_RE.finditer(user_prompt or ""):
        path = (match.group("path") or "").strip()
        body = match.group("body") or ""
        if path or body.strip():
            files.append(EditorFile(path=path or "untitled", body=body))
    return files


def extract_repo_knowledge(user_prompt: str) -> str:
    text = user_prompt or ""
    marker = "[REPO KNOWLEDGE"
    upper = text.upper()
    start = upper.find(marker)
    if start < 0:
        return ""
    chunk = text[start:]
    # cut at next major section if any
    end_markers = ("<<<FILE", "[USER REQUEST]", "[EDITOR CONTEXT]")
    end = len(chunk)
    for m in end_markers:
        idx = chunk.find(m, 1)
        if idx > 0:
            end = min(end, idx)
    return chunk[:end].strip()[:EDITOR_REPO_KNOWLEDGE_CHARS]


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 1}


def _file_relevance(path: str, ask: str) -> float:
    ask_l = (ask or "").lower()
    path_l = path.replace("\\", "/").lower()
    name = path_l.rsplit("/", 1)[-1]
    stem, _, ext = name.rpartition(".")
    score = 0.0
    if name and name in ask_l:
        score += 50.0
    if stem and len(stem) > 2 and stem in ask_l:
        score += 30.0
    if ext and f".{ext}" in ask_l:
        score += 8.0
    # path segment hits
    for part in path_l.split("/"):
        if len(part) > 2 and part in ask_l:
            score += 6.0
    # soft overlap
    overlap = len(_tokens(name) & _tokens(ask))
    score += overlap * 2.0
    return score


def _chunk_file(path: str, body: str) -> list[FileChunk]:
    lines = body.splitlines()
    if not lines:
        return []
    if len(lines) <= EDITOR_CHUNK_LINES:
        return [
            FileChunk(
                path=path,
                start_line=1,
                end_line=len(lines),
                text="\n".join(lines),
            )
        ]

    chunks: list[FileChunk] = []
    step = max(1, EDITOR_CHUNK_LINES - EDITOR_CHUNK_OVERLAP)
    i = 0
    while i < len(lines):
        piece = lines[i : i + EDITOR_CHUNK_LINES]
        start = i + 1
        end = i + len(piece)
        chunks.append(
            FileChunk(
                path=path,
                start_line=start,
                end_line=end,
                text="\n".join(piece),
            )
        )
        if end >= len(lines):
            break
        i += step
    return chunks


def _score_chunk(chunk: FileChunk, ask_tokens: set[str], file_bonus: float) -> float:
    chunk_tokens = _tokens(chunk.text)
    overlap = len(ask_tokens & chunk_tokens)
    # Prefer earlier chunks slightly when scores tie (headers/imports often matter)
    recency_penalty = chunk.start_line / 10000.0
    return file_bonus + overlap * 3.0 - recency_penalty


def select_files(files: list[EditorFile], ask: str) -> list[EditorFile]:
    if not files:
        return []
    ranked = sorted(
        files,
        key=lambda f: (_file_relevance(f.path, ask), -len(f.body)),
        reverse=True,
    )
    # Always keep at least the top file; keep others with score > 0 or top N if all zero
    kept: list[EditorFile] = []
    for f in ranked:
        rel = _file_relevance(f.path, ask)
        if not kept:
            kept.append(f)
            continue
        if rel > 0 and len(kept) < EDITOR_MAX_FILES:
            kept.append(f)
        elif rel == 0 and len(kept) < min(2, EDITOR_MAX_FILES):
            # If ask doesn't name files, keep a couple of smallest open tabs
            continue
    if len(kept) == 1 and len(ranked) > 1 and _file_relevance(ranked[0].path, ask) == 0:
        # No name match — keep smallest few files (more likely the HTML vs a giant py)
        by_size = sorted(files, key=lambda f: len(f.body))[: min(3, EDITOR_MAX_FILES)]
        return by_size
    return kept


def is_context_overflow_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "exceed_context_size" in msg
        or "exceeds the available context" in msg
        or "context size" in msg and "exceed" in msg
    )


def strip_agent_protocol_bloat(user_prompt: str) -> str:
    """Drop extension agent catalog/transcript bloat; keep ask + file blocks for re-pack."""
    text = user_prompt or ""
    upper = text.upper()
    cut = len(text)
    for stop in (
        "[CODING AGENT PROTOCOL",
        "[AVAILABLE TOOLS",
        "[AGENT TOOL TRANSCRIPT",
        "[AGENT LOOP",
        "[CONTINUE — AGENT ROUND",
        "[CONTINUE - AGENT ROUND",
    ):
        idx = upper.find(stop)
        if idx >= 0:
            cut = min(cut, idx)
    head = text[:cut].strip()
    if "<<<FILE" in head:
        return head
    return text.strip()


def _chunk_preview(chunk: FileChunk) -> str:
    flat = " ".join((chunk.text or "").split())
    if len(flat) <= EDITOR_SEQUENTIAL_PREVIEW_CHARS:
        return flat
    return flat[: EDITOR_SEQUENTIAL_PREVIEW_CHARS].rstrip() + "…"


def build_chunk_catalog(
    user_prompt: str,
    *,
    include_previews: bool = True,
) -> tuple[str, dict]:
    """
    Index of file chunks (no bodies) for sequential read mode.
    Returns (catalog_markdown, stats).
    """
    stats: dict = {
        "mode": "sequential_catalog",
        "files_in": 0,
        "chunks_total": 0,
        "approx_tokens": 0,
    }
    ask = extract_user_request(user_prompt)
    files = parse_editor_files(strip_agent_protocol_bloat(user_prompt))
    stats["files_in"] = len(files)
    if not files:
        return "", stats

    kept_files = select_files(files, ask)
    ask_tokens = _tokens(ask)
    entries: list[tuple[str, FileChunk]] = []
    for f in kept_files:
        bonus = _file_relevance(f.path, ask)
        for chunk in _chunk_file(f.path, f.body):
            chunk.score = _score_chunk(chunk, ask_tokens, bonus)
            entries.append((f.path, chunk))

    entries.sort(key=lambda pair: pair[1].score, reverse=True)
    stats["chunks_total"] = len(entries)

    lines = [
        "[CHUNK CATALOG — use read_file with startLine/endLine]",
        "Example tool_call:",
        '```tool_call',
        '{"name":"read_file","arguments":{"path":"index.html","startLine":1,"endLine":160}}',
        "```",
        "",
    ]
    current_path = ""
    for path, chunk in entries:
        if path != current_path:
            if current_path:
                lines.append("")
            body_len = next((len(f.body.splitlines()) for f in kept_files if f.path == path), 0)
            n_chunks = sum(1 for p, _ in entries if p == path)
            lines.append(f"## {path} ({body_len} lines, {n_chunks} chunk(s))")
            current_path = path
        preview = f' — "{_chunk_preview(chunk)}"' if include_previews else ""
        lines.append(
            f"- lines {chunk.start_line}-{chunk.end_line} (score={chunk.score:.1f}){preview}"
        )

    dropped = stats["files_in"] - len(kept_files)
    if dropped > 0:
        lines.insert(
            1,
            f"(Omitted {dropped} unrelated open file(s); call read_file on other paths if needed.)",
        )

    catalog = "\n".join(lines).strip()
    stats["approx_tokens"] = approx_tokens(catalog)
    stats["kept_paths"] = [f.path for f in kept_files]
    return catalog, stats


def pack_editor_context_sequential(
    user_prompt: str,
    *,
    token_budget: int | None = None,
) -> tuple[str, dict]:
    """
    Lightweight prompt for context overflow: task brief + chunk catalog, no file bodies.
    The model should read_file(startLine/endLine) before editing.
    """
    stats: dict = {
        "packed": True,
        "mode": "sequential",
        "files_in": 0,
        "approx_tokens": 0,
    }
    slim = strip_agent_protocol_bloat(user_prompt)
    ask = extract_user_request(slim)
    files = parse_editor_files(slim)
    stats["files_in"] = len(files)
    catalog, cat_stats = build_chunk_catalog(slim)
    stats.update({k: v for k, v in cat_stats.items() if k != "mode"})

    brief = build_task_brief(ask, [f.path for f in files])
    repo = extract_repo_knowledge(slim)

    parts = [
        "[SEQUENTIAL READ MODE — context overflow recovery]",
        "Full file bodies were omitted to fit the model. Fetch chunks with read_file before editing.",
        "",
        brief,
        "",
        f"[USER REQUEST]\n{ask}\n",
    ]
    if repo:
        parts.append(repo)
    if catalog:
        parts.append(catalog)
    else:
        parts.append(
            "[CHUNK CATALOG]\nNo editor file blocks found — use list_dir/search_text/read_file on the repo."
        )

    packed = "\n\n".join(p for p in parts if p).strip()
    budget = token_budget or max(2048, EDITOR_TOKEN_BUDGET // 2)
    if approx_tokens(packed) > budget:
        packed = packed[: budget * _CHARS_PER_TOKEN] + "\n…[catalog truncated for budget]"
    stats["approx_tokens"] = approx_tokens(packed)
    stats["budget"] = budget
    return packed, stats


def pack_editor_context(
    user_prompt: str,
    *,
    token_budget: int | None = None,
) -> tuple[str, dict]:
    """
    Returns (packed_prompt, stats).
    If packing is disabled or this isn't an editor dump, returns the original prompt.
    """
    stats: dict = {
        "packed": False,
        "files_in": 0,
        "files_kept": 0,
        "chunks_kept": 0,
        "approx_tokens": approx_tokens(user_prompt or ""),
    }
    if not EDITOR_PACK_ENABLED or not looks_like_editor_dump(user_prompt):
        return user_prompt, stats

    budget = token_budget or EDITOR_TOKEN_BUDGET
    ask = extract_user_request(user_prompt)
    files = parse_editor_files(user_prompt)
    stats["files_in"] = len(files)
    kept_files = select_files(files, ask)
    stats["files_kept"] = len(kept_files)
    ask_tokens = _tokens(ask)

    ranked_chunks: list[FileChunk] = []
    for f in kept_files:
        bonus = _file_relevance(f.path, ask)
        for chunk in _chunk_file(f.path, f.body):
            chunk.score = _score_chunk(chunk, ask_tokens, bonus)
            ranked_chunks.append(chunk)

    ranked_chunks.sort(key=lambda c: c.score, reverse=True)

    preamble = (
        "The user has editor files attached. Only the most relevant excerpts were kept "
        "to fit the model context.\n\n"
        f"{build_task_brief(ask, [f.path for f in files])}\n\n"
        f"[USER REQUEST]\n{ask}\n"
    )
    repo = extract_repo_knowledge(user_prompt)
    if repo:
        preamble += f"\n{repo}\n"

    used = approx_tokens(preamble)
    chosen_blocks: list[str] = []
    chosen_meta: list[FileChunk] = []
    for chunk in ranked_chunks:
        header = (
            f"<<<FILE path=\"{chunk.path}\" lines={chunk.start_line}-{chunk.end_line}>>>\n"
        )
        footer = "<<<END_FILE>>>\n"
        block = f"\n{header}{chunk.text}\n{footer}"
        cost = approx_tokens(block)
        if chosen_blocks and used + cost > budget:
            continue
        if not chosen_blocks and used + cost > budget:
            remain_chars = max(500, (budget - used - 80) * _CHARS_PER_TOKEN)
            truncated = chunk.text[:remain_chars] + "\n…[truncated]"
            header = (
                f"<<<FILE path=\"{chunk.path}\" "
                f"lines={chunk.start_line}-{chunk.end_line} truncated>>>\n"
            )
            block = f"\n{header}{truncated}\n{footer}"
            chosen_blocks.append(block)
            chosen_meta.append(chunk)
            used += approx_tokens(block)
            break
        chosen_blocks.append(block)
        chosen_meta.append(chunk)
        used += cost
        if used >= budget:
            break

    # Preserve original file order for readability
    order = {f.path: i for i, f in enumerate(kept_files)}
    paired = sorted(
        zip(chosen_meta, chosen_blocks),
        key=lambda pair: (order.get(pair[0].path, 999), pair[0].start_line),
    )
    ordered_blocks = [b for _, b in paired]

    parts = [preamble, "\n[PACKED EDITOR CONTEXT]\n"]
    dropped = stats["files_in"] - stats["files_kept"]
    if dropped > 0:
        parts.append(
            f"(Omitted {dropped} unrelated open file(s) that did not match the request.)\n"
        )
    parts.extend(ordered_blocks)

    packed = "".join(parts).strip()
    stats.update(
        {
            "packed": True,
            "chunks_kept": len(chosen_meta),
            "approx_tokens": approx_tokens(packed),
            "budget": budget,
            "ask": ask[:200],
            "kept_paths": list(dict.fromkeys(c.path for c in chosen_meta)),
        }
    )
    return packed, stats


def iter_chunk_summaries(chunks: Iterable[FileChunk]) -> list[str]:
    return [f"{c.path}:{c.start_line}-{c.end_line} (score={c.score:.1f})" for c in chunks]
