"""
Pluggable web search for ChatRouter.

Providers (set WEB_SEARCH_PROVIDER):
  - duckduckgo  (default, no API key)
  - brave       (BRAVE_SEARCH_API_KEY)
  - serper      (SERPER_API_KEY)  — Google-quality results via Serper
  - bing        (BING_SEARCH_API_KEY)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests
from dotenv import load_dotenv
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
load_dotenv(SCRIPT_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WEB_SEARCH_PROVIDER = os.getenv("WEB_SEARCH_PROVIDER", "duckduckgo").strip().lower()
WEB_SEARCH_MAX_RESULTS = max(1, int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5")))
WEB_SEARCH_ON_CODING = os.getenv("WEB_SEARCH_ON_CODING", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "").strip()
BING_SEARCH_API_KEY = os.getenv("BING_SEARCH_API_KEY", "").strip()

SEARCH_TRIGGER_KEYWORDS = (
    "search for",
    "google",
    "bing",
    "look up",
    "lookup",
    "latest",
    "current version",
    "according to",
    "what does the docs",
    "documentation",
    "stackoverflow",
    "from the web",
)


def should_search(user_prompt: str, *, coding: bool = False) -> bool:
    if not WEB_SEARCH_ENABLED:
        return False
    text = (user_prompt or "").lower()
    if any(kw in text for kw in SEARCH_TRIGGER_KEYWORDS):
        return True
    # Editor-attached coding dumps are local work — don't web-search the whole buffer
    # unless the user explicitly asked to search (keywords above).
    if "<<<file" in text or "[editor context]" in text:
        return False
    if coding and WEB_SEARCH_ON_CODING:
        return True
    return False


def _normalize_results(raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for item in raw:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or item.get("link") or "").strip()
        snippet = str(
            item.get("snippet") or item.get("description") or item.get("body") or ""
        ).strip()
        if not (title or snippet or url):
            continue
        cleaned.append({"title": title, "url": url, "snippet": snippet})
    return cleaned[:WEB_SEARCH_MAX_RESULTS]


def _search_duckduckgo(query: str) -> list[dict[str, str]]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS  # type: ignore

    rows: list[dict[str, Any]] = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=WEB_SEARCH_MAX_RESULTS):
            rows.append(
                {
                    "title": item.get("title"),
                    "url": item.get("href") or item.get("link"),
                    "snippet": item.get("body"),
                }
            )
    return _normalize_results(rows)


def _search_brave(query: str) -> list[dict[str, str]]:
    if not BRAVE_SEARCH_API_KEY:
        raise RuntimeError("BRAVE_SEARCH_API_KEY is not set")
    response = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
        },
        params={"q": query, "count": WEB_SEARCH_MAX_RESULTS},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    rows = []
    for item in (data.get("web") or {}).get("results") or []:
        rows.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "snippet": item.get("description"),
            }
        )
    return _normalize_results(rows)


def _search_serper(query: str) -> list[dict[str, str]]:
    """Serper.dev — Google results via API."""
    if not SERPER_API_KEY:
        raise RuntimeError("SERPER_API_KEY is not set")
    response = requests.post(
        "https://google.serper.dev/search",
        headers={
            "X-API-KEY": SERPER_API_KEY,
            "Content-Type": "application/json",
        },
        json={"q": query, "num": WEB_SEARCH_MAX_RESULTS},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    rows = []
    for item in data.get("organic") or []:
        rows.append(
            {
                "title": item.get("title"),
                "url": item.get("link"),
                "snippet": item.get("snippet"),
            }
        )
    return _normalize_results(rows)


def _search_bing(query: str) -> list[dict[str, str]]:
    if not BING_SEARCH_API_KEY:
        raise RuntimeError("BING_SEARCH_API_KEY is not set")
    response = requests.get(
        "https://api.bing.microsoft.com/v7.0/search",
        headers={"Ocp-Apim-Subscription-Key": BING_SEARCH_API_KEY},
        params={"q": query, "count": WEB_SEARCH_MAX_RESULTS},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    rows = []
    for item in (data.get("webPages") or {}).get("value") or []:
        rows.append(
            {
                "title": item.get("name"),
                "url": item.get("url"),
                "snippet": item.get("snippet"),
            }
        )
    return _normalize_results(rows)


def web_search(query: str, provider: str | None = None) -> list[dict[str, str]]:
    """Run a web search and return [{title, url, snippet}, ...]."""
    if not WEB_SEARCH_ENABLED:
        return []
    q = (query or "").strip()
    if not q:
        return []

    chosen = (provider or WEB_SEARCH_PROVIDER).strip().lower()
    logger.info("web_search provider=%s query=%r", chosen, q[:120])

    if chosen in {"duckduckgo", "ddg"}:
        return _search_duckduckgo(q)
    if chosen == "brave":
        return _search_brave(q)
    if chosen in {"serper", "google"}:
        # "google" maps to Serper (official Google CSE needs cx + key; Serper is simpler)
        return _search_serper(q)
    if chosen == "bing":
        return _search_bing(q)
    raise ValueError(f"Unknown WEB_SEARCH_PROVIDER: {chosen}")


def format_search_results_for_prompt(results: list[dict[str, str]]) -> str:
    if not results:
        return ""
    lines = ["[WEB SEARCH RESULTS — use carefully; verify before trusting]"]
    for index, item in enumerate(results, start=1):
        lines.append(
            f"{index}. {item.get('title') or '(no title)'}\n"
            f"   URL: {item.get('url') or '(no url)'}\n"
            f"   {item.get('snippet') or ''}"
        )
    return "\n".join(lines)
