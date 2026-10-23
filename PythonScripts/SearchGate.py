"""
Need-based web search gate (no model call — deciding must cost less than searching).

Each request is scored on signals that local knowledge is likely stale or missing:

  explicit  (+3)  user asked to search / check docs / look it up
  volatile  (+2)  latest / current version / deprecated / changelog / recent year / news
  version   (+1)  pinned library version (pkg@1.2, v5, react 19.1)
  error     (+1)  third-party error code or traceback from an installed package
  service   (+1)  hosted API / SDK whose surface changes (stripe, openai, discord, …)
  external  (+1)  casual question about the outside world (weather, scores, prices, …)

Requests on attached editor code need explicit or volatile signals to search. Task verbs
(write/refactor/fix/explain …) cost 1 point unless explicit or volatile. A close prior web memory
covers non-volatile needs. Search when score >= SEARCH_GATE_THRESHOLD (default 2).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date

from EditorContext import extract_user_request, looks_like_editor_dump

SEARCH_GATE_THRESHOLD = max(1, int(os.getenv("SEARCH_GATE_THRESHOLD", "2")))
PRIOR_WEB_MAX_DISTANCE = float(os.getenv("SEARCH_GATE_PRIOR_DISTANCE", "0.25"))

EXPLICIT_RE = re.compile(
    r"\b(search(?: the web| online| for)?|google|bing|look (?:it |this |that )?up|lookup|"
    r"check (?:the )?docs|official docs|documentation for|stack ?overflow|"
    r"from the web|on the web|search online|web search|find (?:me )?(?:a |the )?(?:link|source|article))\b",
    re.I,
)
VOLATILE_RE = re.compile(
    r"\b(latest|newest|most recent|current(?:ly)? (?:version|release|api|docs|price)|"
    r"up[- ]to[- ]date|as of|nowadays|these days|this (?:week|month|year)|"
    r"recently|just released|new release|release notes|changelog|deprecated|deprecation|"
    r"breaking changes?|end of life|eol|still supported|recommended way now|news)\b",
    re.I,
)
VERSION_RE = re.compile(
    r"(?:\b[a-z][\w.-]{1,30}@\^?~?\d+(?:\.\d+){0,2}\b)"
    r"|(?:\b[a-z][\w-]{1,30}\s+v\d+(?:\.\d+){0,2}\b)"
    r"|(?:\b[a-z][\w-]{1,30}\s+\d+\.\d+(?:\.\d+)?\b)",
    re.I,
)
ERROR_CODE_RE = re.compile(
    r"\b(?:[A-Z]{2,5}\d{3,5}|ERR_[A-Z_]{3,}|"
    r"E(?:NOENT|ACCES|PERM|ADDRINUSE|CONNREFUSED|CONNRESET|TIMEDOUT)|0x[0-9a-fA-F]{6,})\b"
)
TRACEBACK_RE = re.compile(
    r"(site-packages|node_modules|Traceback \(most recent call last\)|"
    r"ModuleNotFoundError|ImportError|Cannot find module|npm ERR!|pip install)",
    re.I,
)
SERVICE_RE = re.compile(
    r"\b(stripe|openai|anthropic|aws|azure|gcp|google cloud|firebase|supabase|vercel|"
    r"netlify|cloudflare|discord(?:\.py| api| bot)?|slack api|telegram bot|twitch api|"
    r"youtube api|spotify api|github api|github actions|twilio|sendgrid|shopify|"
    r"huggingface|hugging face|steam api|roblox api)\b",
    re.I,
)
EXTERNAL_WORLD_RE = re.compile(
    r"\b(weather|forecast|score|scores|who won|stock price|exchange rate|price of|"
    r"release date|box office|election|schedule for|open now|near me|population of)\b",
    re.I,
)
SELF_CONTAINED_RE = re.compile(
    r"^\s*(please\s+)?(write|create|make|implement|add|remove|delete|rename|refactor|"
    r"fix|clean ?up|convert|optimi[sz]e|explain|comment|format|reorder|simplify|"
    r"generate|build|test|debug)\b",
    re.I,
)
YEAR_RE = re.compile(r"\b(20\d{2})\b")


@dataclass
class SearchDecision:
    search: bool
    score: int
    reasons: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        if not self.reasons:
            return "no outside-knowledge signal"
        return ", ".join(self.reasons)


def _recent_year(text: str) -> bool:
    this_year = date.today().year
    return any(int(y) >= this_year - 1 for y in YEAR_RE.findall(text))


def assess_search_need(
    user_prompt: str,
    *,
    coding: bool = False,
    prior_hits: list[dict] | None = None,
) -> SearchDecision:
    text = user_prompt or ""
    focus = extract_user_request(text).strip()
    if not focus:
        return SearchDecision(False, 0, ["empty request"])

    score = 0
    reasons: list[str] = []

    explicit = bool(EXPLICIT_RE.search(focus))
    if explicit:
        score += 3
        reasons.append("asked to look it up")

    volatile = bool(VOLATILE_RE.search(focus)) or _recent_year(focus)
    if volatile:
        score += 2
        reasons.append("time-sensitive")

    if VERSION_RE.search(focus):
        score += 1
        reasons.append("pinned version")

    if ERROR_CODE_RE.search(focus) or TRACEBACK_RE.search(focus):
        score += 1
        reasons.append("third-party error")

    if SERVICE_RE.search(focus):
        score += 1
        reasons.append("hosted API")

    if not coding and EXTERNAL_WORLD_RE.search(focus):
        score += 2
        reasons.append("outside-world fact")

    editorish = looks_like_editor_dump(text) or "[editor context]" in text.lower()
    if editorish and not (explicit or volatile):
        return SearchDecision(False, score, reasons + ["works on attached code"])
    if SELF_CONTAINED_RE.search(focus) and not (explicit or volatile):
        score -= 1
        reasons.append("self-contained task")

    if (
        not explicit
        and not volatile
        and prior_hits
        and any(
            (h.get("distance") is not None and h["distance"] <= PRIOR_WEB_MAX_DISTANCE)
            for h in prior_hits
        )
    ):
        return SearchDecision(False, score, reasons + ["covered by prior web memory"])

    return SearchDecision(score >= SEARCH_GATE_THRESHOLD, score, reasons)
