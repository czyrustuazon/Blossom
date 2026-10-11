"""
Gated multi-agent research pipeline for ChatRouter and /v1/research clients.

Modes:
  skip   — prior web_knowledge only (or empty)
  simple — one focused live search (legacy path)
  deep   — planner → parallel searches → optional page fetch → synthesizer
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
load_dotenv(SCRIPT_DIR / ".env", override=True)
load_dotenv(PROJECT_ROOT / ".env", override=True)

from EditorContext import extract_user_request, looks_like_editor_dump
from PromptTier import PromptTier, detect_prompt_tier
from SemanticMemory import (
    COLLECTION_WEB,
    format_memories_for_prompt,
    learn_web_findings,
    query_memories,
)
from WebSearch import (
    SEARCH_TRIGGER_KEYWORDS,
    WEB_SEARCH_ENABLED,
    WEB_SEARCH_PROVIDER,
    format_search_results_for_prompt,
    should_search,
    web_search,
)

logger = logging.getLogger(__name__)

ProgressFn = Callable[[dict[str, Any]], None]
CompleteFn = Callable[[list[dict[str, str]], float], str]

RESEARCH_PIPELINE_ENABLED = os.getenv(
    "RESEARCH_PIPELINE_ENABLED", "true"
).strip().lower() in {"1", "true", "yes", "on"}
RESEARCH_DEEP_ENABLED = os.getenv(
    "RESEARCH_DEEP_ENABLED", "true"
).strip().lower() in {"1", "true", "yes", "on"}
RESEARCH_MAX_QUERIES = max(1, int(os.getenv("RESEARCH_MAX_QUERIES", "4")))
RESEARCH_MAX_ROUNDS = max(1, int(os.getenv("RESEARCH_MAX_ROUNDS", "1")))
RESEARCH_FETCH_PAGES = os.getenv(
    "RESEARCH_FETCH_PAGES", "false"
).strip().lower() in {"1", "true", "yes", "on"}
RESEARCH_TIMEOUT_SEC = max(5, int(os.getenv("RESEARCH_TIMEOUT_SEC", "45")))
RESEARCH_FETCH_MAX_PAGES = max(0, int(os.getenv("RESEARCH_FETCH_MAX_PAGES", "2")))
RESEARCH_FETCH_MAX_CHARS = max(200, int(os.getenv("RESEARCH_FETCH_MAX_CHARS", "1200")))

DEEP_KEYWORDS = (
    "research",
    "compare sources",
    "compare options",
    "latest docs",
    "documentation",
    "cite",
    "citation",
    "citations",
    "sources for",
    "what changed in",
    "breaking change",
    "migration guide",
    " pros and cons",
    "pros/cons",
    "versus",
    " vs ",
    "survey",
    "deep dive",
    "look into",
    "investigate",
)

VERSION_API_RE = re.compile(
    r"\b("
    r"latest version|current version|which version|api (?:for|of)|"
    r"breaking changes?|deprecated|changelog|release notes|"
    r"how (?:do|does) .+ (?:work|work now)|docs? for"
    r")\b",
    re.I,
)
LIB_TOKEN_RE = re.compile(
    r"\b([a-z][a-z0-9_-]{2,}(?:\.[a-z0-9_-]+)?)\b",
    re.I,
)
COMMON_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "what",
    "when",
    "where",
    "how",
    "can",
    "you",
    "please",
    "need",
    "want",
    "using",
    "into",
    "about",
    "have",
    "does",
    "should",
    "would",
    "could",
    "just",
    "also",
    "like",
    "make",
    "code",
    "file",
    "files",
    "function",
    "class",
    "error",
    "fix",
    "help",
    "look",
    "search",
    "google",
    "docs",
    "documentation",
    "latest",
    "version",
    "current",
    "research",
    "compare",
    "sources",
    "citation",
    "citations",
}

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*?\]")
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*?\}")


@dataclass
class ResearchResult:
    brief: str = ""
    mode: str = "skip"
    sources: list[dict[str, str]] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)


def _think(
    on_progress: ProgressFn | None,
    step: str,
    message: str,
    **extra: Any,
) -> None:
    event = {
        "object": "blossom.thought",
        "step": step,
        "message": message,
        "ts": time.time(),
        **extra,
    }
    logger.info("research step=%s %s", step, message)
    if on_progress:
        on_progress(event)


def _prior_web_block(focus: str, on_progress: ProgressFn | None) -> str:
    _think(on_progress, "web_memory", "Checking prior web knowledge…")
    prior = query_memories(focus, collection=COLLECTION_WEB)
    if not prior:
        return ""
    _think(
        on_progress,
        "web_memory",
        f"Loaded {len(prior)} prior web memory(ies).",
        count=len(prior),
    )
    return format_memories_for_prompt(
        prior,
        heading="[PRIOR WEB KNOWLEDGE — from earlier searches]",
    )


def _has_search_keywords(text: str) -> bool:
    lower = (text or "").lower()
    return any(kw in lower for kw in SEARCH_TRIGGER_KEYWORDS)


def _count_lib_hints(text: str) -> int:
    tokens = {
        m.group(1).lower()
        for m in LIB_TOKEN_RE.finditer(text or "")
        if m.group(1).lower() not in COMMON_WORDS and len(m.group(1)) > 3
    }
    # Prefer tokens that look like package names (hyphen/underscore/dot).
    scored = [t for t in tokens if "-" in t or "_" in t or "." in t]
    return len(scored) if scored else 0


def classify_research_need(user_prompt: str, *, coding: bool = False) -> str:
    """Return skip | simple | deep."""
    if not WEB_SEARCH_ENABLED:
        return "skip"

    text = user_prompt or ""
    focus = extract_user_request(text)
    lower = focus.lower()
    tier = detect_prompt_tier(text)

    if tier == PromptTier.TINY:
        return "skip"

    editorish = looks_like_editor_dump(text) or "[editor context]" in text.lower()
    if editorish and not _has_search_keywords(text):
        return "skip"

    deep_hit = any(kw in lower for kw in DEEP_KEYWORDS) or bool(
        VERSION_API_RE.search(focus)
    )
    multi_lib = _count_lib_hints(focus) >= 2
    wants_citations = any(
        w in lower for w in ("cite", "citation", "citations", "with sources", "sources?")
    )

    if RESEARCH_DEEP_ENABLED and (deep_hit or multi_lib or wants_citations):
        return "deep"

    if should_search(text, coding=coding):
        return "simple"

    # Trivial chitchat / no search signal
    if len(focus.strip()) < 12 and not _has_search_keywords(text):
        return "skip"

    return "skip"


def parse_planner_queries(raw: str, *, max_queries: int | None = None) -> list[str]:
    """Extract query strings from planner LLM output (JSON array/object or lines)."""
    limit = max_queries if max_queries is not None else RESEARCH_MAX_QUERIES
    text = (raw or "").strip()
    if not text:
        return []

    candidates: list[str] = []

    for match in (_JSON_ARRAY_RE.search(text), _JSON_OBJECT_RE.search(text)):
        if not match:
            continue
        blob = match.group(0)
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str) and item.strip():
                    candidates.append(item.strip())
                elif isinstance(item, dict):
                    q = item.get("query") or item.get("q") or item.get("text")
                    if isinstance(q, str) and q.strip():
                        candidates.append(q.strip())
        elif isinstance(data, dict):
            queries = data.get("queries") or data.get("query") or data.get("searches")
            if isinstance(queries, str) and queries.strip():
                candidates.append(queries.strip())
            elif isinstance(queries, list):
                for item in queries:
                    if isinstance(item, str) and item.strip():
                        candidates.append(item.strip())
                    elif isinstance(item, dict):
                        q = item.get("query") or item.get("q")
                        if isinstance(q, str) and q.strip():
                            candidates.append(q.strip())
        if candidates:
            break

    if not candidates:
        for line in text.splitlines():
            cleaned = re.sub(r"^[\s\-\*\d\.\)\(]+", "", line).strip().strip("\"'")
            if 8 <= len(cleaned) <= 200 and not cleaned.lower().startswith(
                ("here", "sure", "i will", "queries", "{", "}")
            ):
                candidates.append(cleaned)

    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for q in candidates:
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
        if len(out) >= limit:
            break
    return out


def _heuristic_queries(focus: str, *, max_queries: int | None = None) -> list[str]:
    limit = max_queries if max_queries is not None else RESEARCH_MAX_QUERIES
    focus = (focus or "").strip()
    if not focus:
        return []
    queries = [focus[:240]]
    libs = [
        m.group(1)
        for m in LIB_TOKEN_RE.finditer(focus)
        if m.group(1).lower() not in COMMON_WORDS
    ][:3]
    for lib in libs:
        queries.append(f"{lib} documentation")
    if " vs " in focus.lower() or "versus" in focus.lower():
        queries.append(f"{focus[:120]} comparison")
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
        if len(out) >= limit:
            break
    return out


def plan_queries(
    focus: str,
    *,
    complete_fn: CompleteFn | None = None,
    max_queries: int | None = None,
    on_progress: ProgressFn | None = None,
) -> list[str]:
    limit = max_queries if max_queries is not None else RESEARCH_MAX_QUERIES
    fallback = _heuristic_queries(focus, max_queries=limit)
    if complete_fn is None:
        return fallback

    _think(on_progress, "research_plan", "Planning research queries…")
    prompt = (
        "You are a research planner. Given the user question, output ONLY a JSON object:\n"
        '{"queries": ["...", "..."]}\n'
        f"Use 2-{limit} short web search queries that together answer the question. "
        "No commentary.\n\n"
        f"Question:\n{focus[:1500]}"
    )
    try:
        raw = complete_fn(
            [
                {"role": "system", "content": "Output JSON only."},
                {"role": "user", "content": prompt},
            ],
            0.2,
        )
        parsed = parse_planner_queries(raw, max_queries=limit)
        if parsed:
            _think(
                on_progress,
                "research_plan",
                f"Planned {len(parsed)} quer(ies).",
                count=len(parsed),
            )
            return parsed
    except Exception as exc:
        logger.warning("research planner failed: %s", exc)
        _think(on_progress, "research_plan", f"Planner failed; using heuristics ({exc})")

    return fallback


def run_searches(
    queries: list[str],
    *,
    on_progress: ProgressFn | None = None,
    timeout_sec: float | None = None,
) -> list[dict[str, str]]:
    timeout = timeout_sec if timeout_sec is not None else float(RESEARCH_TIMEOUT_SEC)
    if not queries:
        return []

    _think(
        on_progress,
        "research_search",
        f"Searching the web ({WEB_SEARCH_PROVIDER}) for {len(queries)} quer(ies)…",
        provider=WEB_SEARCH_PROVIDER,
        count=len(queries),
    )

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    deadline = time.time() + timeout

    def _one(q: str) -> list[dict[str, str]]:
        if time.time() > deadline:
            return []
        try:
            return web_search(q)
        except Exception as exc:
            logger.warning("web_search failed for %r: %s", q[:80], exc)
            return []

    workers = min(4, max(1, len(queries)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="research") as pool:
        futures = {pool.submit(_one, q): q for q in queries}
        for fut in as_completed(futures, timeout=max(1.0, timeout)):
            if time.time() > deadline:
                break
            for item in fut.result() or []:
                url = (item.get("url") or "").strip()
                key = url or f"{item.get('title')}|{item.get('snippet')}"
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                results.append(item)

    _think(
        on_progress,
        "research_search",
        f"Got {len(results)} unique result(s).",
        count=len(results),
    )
    return results


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        piece = data.strip()
        if piece:
            self._chunks.append(piece)

    def text(self) -> str:
        return " ".join(self._chunks)


def _fetch_page_text(url: str, *, max_chars: int) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    try:
        resp = requests.get(
            url,
            timeout=12,
            headers={"User-Agent": "BlossomResearch/1.0"},
        )
        resp.raise_for_status()
        ctype = (resp.headers.get("content-type") or "").lower()
        if "html" not in ctype and "text" not in ctype:
            return ""
        parser = _TextExtractor()
        parser.feed(resp.text[:200_000])
        return parser.text()[:max_chars]
    except Exception as exc:
        logger.debug("page fetch failed %s: %s", url, exc)
        return ""


def fetch_page_summaries(
    sources: list[dict[str, str]],
    *,
    max_pages: int | None = None,
    on_progress: ProgressFn | None = None,
) -> list[dict[str, str]]:
    if not RESEARCH_FETCH_PAGES:
        return []
    limit = RESEARCH_FETCH_MAX_PAGES if max_pages is None else max_pages
    if limit <= 0:
        return []

    _think(on_progress, "research_fetch", f"Fetching up to {limit} page(s)…")
    enriched: list[dict[str, str]] = []
    for item in sources[:limit]:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        body = _fetch_page_text(url, max_chars=RESEARCH_FETCH_MAX_CHARS)
        if not body:
            continue
        enriched.append(
            {
                "title": item.get("title") or url,
                "url": url,
                "snippet": body,
            }
        )
    _think(
        on_progress,
        "research_fetch",
        f"Fetched {len(enriched)} page excerpt(s).",
        count=len(enriched),
    )
    return enriched


def synthesize_brief(
    focus: str,
    results: list[dict[str, str]],
    *,
    complete_fn: CompleteFn | None = None,
    on_progress: ProgressFn | None = None,
) -> str:
    if not results:
        return ""

    formatted = format_search_results_for_prompt(results)
    if complete_fn is None:
        return formatted

    _think(on_progress, "research_synth", "Synthesizing research brief…")
    prompt = (
        "Synthesize a concise research brief for the coding/assistant model.\n"
        "- Bullet facts that answer the question\n"
        "- Note conflicts between sources\n"
        "- Include short citations as (title — url)\n"
        "- Max ~400 words\n\n"
        f"Question:\n{focus[:1200]}\n\n"
        f"Sources:\n{formatted[:6000]}"
    )
    try:
        summary = complete_fn(
            [
                {
                    "role": "system",
                    "content": "You write concise cited research briefs. No fluff.",
                },
                {"role": "user", "content": prompt},
            ],
            0.25,
        ).strip()
        if summary:
            return (
                "[RESEARCH BRIEF — verify before trusting]\n"
                f"{summary}\n\n"
                f"{formatted}"
            )
    except Exception as exc:
        logger.warning("research synth failed: %s", exc)
        _think(on_progress, "research_synth", f"Synth failed; using raw results ({exc})")

    return formatted


def run_simple_search(
    focus: str,
    *,
    on_progress: ProgressFn | None = None,
) -> tuple[str, list[dict[str, str]]]:
    _think(
        on_progress,
        "web_search",
        f"Searching the web ({WEB_SEARCH_PROVIDER}) for: {focus[:80]!r}…",
        provider=WEB_SEARCH_PROVIDER,
    )
    try:
        results = web_search(focus)
    except Exception as exc:
        logger.warning("Web search failed: %s", exc)
        _think(on_progress, "web_search_error", f"Web search failed: {exc}")
        return "", []

    if not results:
        _think(on_progress, "web_search", "No web results.")
        return "", []

    _think(
        on_progress,
        "web_search",
        f"Got {len(results)} result(s); storing in web_knowledge…",
        count=len(results),
    )
    learn_web_findings(
        focus,
        results,
        source_provider=WEB_SEARCH_PROVIDER,
    )
    return format_search_results_for_prompt(results), results


def run_research_pipeline(
    user_prompt: str,
    *,
    coding: bool = False,
    on_progress: ProgressFn | None = None,
    complete_fn: CompleteFn | None = None,
    force_mode: str | None = None,
) -> ResearchResult:
    """
    Run gated research. Returns ResearchResult with prompt-ready brief.
    When RESEARCH_PIPELINE_ENABLED is false, callers should use the simple path only.
    """
    focus = extract_user_request(user_prompt)
    prior = _prior_web_block(focus, on_progress)
    mode = force_mode or classify_research_need(user_prompt, coding=coding)

    if not RESEARCH_PIPELINE_ENABLED and mode == "deep":
        mode = "simple" if should_search(user_prompt, coding=coding) else "skip"

    _think(on_progress, "research_gate", f"Research mode: {mode}", mode=mode)

    if mode == "skip":
        return ResearchResult(brief=prior, mode="skip", sources=[], queries=[])

    if mode == "simple" or not RESEARCH_DEEP_ENABLED:
        block, sources = run_simple_search(focus, on_progress=on_progress)
        parts = [p for p in (prior, block) if p]
        return ResearchResult(
            brief="\n\n".join(parts),
            mode="simple",
            sources=sources,
            queries=[focus] if block else [],
        )

    # deep
    queries = plan_queries(
        focus,
        complete_fn=complete_fn,
        on_progress=on_progress,
    )
    all_sources: list[dict[str, str]] = []
    brief_parts: list[str] = []
    if prior:
        brief_parts.append(prior)

    rounds = RESEARCH_MAX_ROUNDS
    for round_idx in range(rounds):
        if round_idx > 0 and complete_fn is not None:
            # Optional second round: ask for follow-up queries from gaps
            follow = plan_queries(
                focus + "\n\nPrior results were incomplete; find follow-up queries.",
                complete_fn=complete_fn,
                on_progress=on_progress,
            )
            queries = follow or queries

        sources = run_searches(queries, on_progress=on_progress)
        pages = fetch_page_summaries(sources, on_progress=on_progress)
        merged = sources + pages
        all_sources.extend(merged)
        if not merged:
            continue
        brief_parts.append(
            synthesize_brief(
                focus,
                merged,
                complete_fn=complete_fn,
                on_progress=on_progress,
            )
        )
        break  # default one successful round is enough

    summary_for_learn = ""
    if brief_parts:
        # Last synth/raw block (exclude prior memory heading for storage)
        for part in reversed(brief_parts):
            if part.startswith("[PRIOR WEB"):
                continue
            summary_for_learn = part[:4000]
            break

    if all_sources:
        learn_web_findings(
            focus,
            all_sources,
            summary=summary_for_learn or None,
            source_provider=f"research:{WEB_SEARCH_PROVIDER}",
        )

    return ResearchResult(
        brief="\n\n".join(p for p in brief_parts if p),
        mode="deep",
        sources=all_sources,
        queries=queries,
    )
