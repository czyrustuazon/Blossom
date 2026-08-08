"""
Compress coding context once before ChatRouter cloud fallback (P2).

Mirrors Blossom Assistant src/escalate/compressHandoff.ts + buildCloudHandoff.ts:
  - Rules-based summary of editor dumps / local attempts
  - Optional LLM summarize when raw context exceeds threshold
  - Same blob reused for Gemini → Claude in _cloud_facts()
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable

from EditorContext import extract_user_request

logger = logging.getLogger(__name__)

SESSION_SUMMARY_MARKER = "[BLOSSOM SESSION SUMMARY"
HANDOFF_MAX_SUMMARY_CHARS = max(
    2000, int(os.getenv("HANDOFF_MAX_SUMMARY_CHARS", "6000"))
)
HANDOFF_SUMMARIZE_THRESHOLD_CHARS = max(
    4000, int(os.getenv("HANDOFF_SUMMARIZE_THRESHOLD_CHARS", "12000"))
)
HANDOFF_SUMMARIZE_PROVIDER = (
    os.getenv("HANDOFF_SUMMARIZE_PROVIDER", "local").strip().lower()
)

_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_EDITOR_CTX_RE = re.compile(
    r"\[EDITOR CONTEXT\][\s\S]*?(?=\n\n|\n\[|$)", re.IGNORECASE
)
_REPO_KNOWLEDGE_RE = re.compile(
    r"\[REPO KNOWLEDGE\][\s\S]*?(?=\n\n|\n\[|$)", re.IGNORECASE
)
_PATH_RE = re.compile(
    r"(?:^|[\s\"'(])([\w.-]+(?:/|\\)[\w./\\-]+\.\w{1,8})"
)
_ESCALATE_REASON_RE = re.compile(
    r"ESCALATE_(?:CLOUD|GEMINI|CURSOR|CLAUDE)\s*:?\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)

SummarizeFn = Callable[[str], str | None]


def _strip_noise(text: str) -> str:
    t = _CODE_BLOCK_RE.sub("[code block omitted]", text or "")
    t = re.sub(r"### Summary[\s\S]*$", "", t, flags=re.IGNORECASE)
    t = _EDITOR_CTX_RE.sub("[editor context omitted]", t)
    t = _REPO_KNOWLEDGE_RE.sub("[repo knowledge omitted]", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _extract_paths(text: str, limit: int = 24) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _PATH_RE.finditer(text or ""):
        path = (match.group(1) or "").replace("\\", "/").strip()
        if len(path) < 3 or len(path) > 200:
            continue
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(path)
        if len(found) >= limit:
            break
    return found


def _escalate_reason(local_attempt: str) -> str:
    match = _ESCALATE_REASON_RE.search(local_attempt or "")
    if not match:
        return ""
    return match.group(1).strip().split("\n")[0][:400]


def already_compressed(text: str) -> bool:
    return SESSION_SUMMARY_MARKER.lower() in (text or "").lower()


def _build_rules_summary(
    *,
    user_ask: str,
    enriched: str,
    local_attempt: str,
    web_block: str,
) -> str:
    stripped = _strip_noise(enriched)
    paths = _extract_paths(stripped + "\n" + (local_attempt or ""))
    failures: list[str] = []
    if local_attempt.strip():
        failures.append(_strip_noise(local_attempt)[:800])
    if web_block.strip():
        failures.append(
            "[Web research context]\n" + _strip_noise(web_block)[:1200]
        )

    reason = _escalate_reason(local_attempt)
    parts = [
        "[BLOSSOM SESSION SUMMARY — compressed for handoff]",
        f"Goal: {user_ask[:400]}",
    ]
    if reason:
        parts.append(f"Escalation reason: {reason}")
    if paths:
        parts.append(
            "Files mentioned / edited:\n"
            + "\n".join(f"- {p}" for p in paths)
        )
    if failures:
        parts.append("Local attempts & context:\n" + "\n\n".join(failures))
    parts.extend(
        [
            f"Raw context chars: {len(enriched)}",
            "",
            "Recent context (trimmed):",
            stripped[-4000:],
        ]
    )
    return "\n".join(parts)


def _local_summarize(raw_summary: str) -> str | None:
    try:
        from MemoryUpdater import chat_completion

        prompt = (
            "Compress this Blossom coding session into a handoff summary.\n"
            "Keep: goal, key decisions, files touched, failures, open questions.\n"
            "Max 1200 words. Plain text only.\n\n"
            + raw_summary[:24000]
        )
        text = chat_completion(
            [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            temperature=0.2,
            timeout=120.0,
        )
        return (text or "").strip() or None
    except Exception as exc:
        logger.warning("Local handoff summarize failed: %s", exc)
        return None


def build_cloud_handoff_prompt(
    *,
    summary_markdown: str,
    user_text: str,
    local_attempt: str = "",
    web_block: str = "",
    prior_provider_attempt: tuple[str, str] | None = None,
) -> str:
    preamble = (
        "You are a text-only coding advisor (no tools). "
        "Provide a clear, actionable answer. Use fenced code blocks with path= when edits are needed."
    )
    parts = [
        preamble,
        "",
        summary_markdown.strip(),
        "",
        f"Current user ask (verbatim):\n{user_text.strip()}",
    ]
    if local_attempt.strip():
        parts.extend(["", f"Local Blossom attempt:\n{local_attempt.strip()[:4000]}"])
    if web_block.strip() and SESSION_SUMMARY_MARKER not in web_block:
        parts.extend(
            [
                "",
                "Web research (trimmed):",
                _strip_noise(web_block)[:1500],
            ]
        )
    if prior_provider_attempt:
        provider, text = prior_provider_attempt
        parts.extend(
            [
                "",
                f"[PRIOR ESCALATION ATTEMPT — {provider}]",
                "The user already tried the provider below. Continue from the session summary; do not restart.",
                text[:3000],
            ]
        )
    return "\n".join(parts)


def prepare_cloud_coding_prompt(
    user_prompt: str,
    *,
    enriched: str,
    local_attempt: str = "",
    web_block: str = "",
    summarize_fn: SummarizeFn | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Build a cloud-sized prompt from a full coding context pack.

    Returns (cloud_prompt, stats). Skips re-compression when the caller already
    prefixed [BLOSSOM SESSION SUMMARY] (extension Option A).
    """
    user_ask = extract_user_request(user_prompt)
    raw_chars = len(enriched or "")

    if already_compressed(user_prompt) or already_compressed(enriched):
        summary_md = _extract_session_summary(user_prompt) or _extract_session_summary(
            enriched
        )
        if not summary_md:
            summary_md = _strip_noise(user_prompt or enriched)[:HANDOFF_MAX_SUMMARY_CHARS]
        cloud_prompt = build_cloud_handoff_prompt(
            summary_markdown=summary_md,
            user_text=user_ask,
            local_attempt=local_attempt,
            web_block=web_block,
        )
        return cloud_prompt, {
            "skipped": True,
            "reason": "already_compressed",
            "raw_chars": raw_chars,
            "compressed_chars": len(summary_md),
            "cloud_prompt_chars": len(cloud_prompt),
        }

    summary = _build_rules_summary(
        user_ask=user_ask,
        enriched=enriched,
        local_attempt=local_attempt,
        web_block=web_block,
    )

    provider = HANDOFF_SUMMARIZE_PROVIDER
    if raw_chars > HANDOFF_SUMMARIZE_THRESHOLD_CHARS and provider != "rules-only":
        llm_text: str | None = None
        if summarize_fn is not None:
            llm_text = summarize_fn(summary)
        elif provider == "local":
            llm_text = _local_summarize(summary)
        if llm_text:
            summary = (
                "[BLOSSOM SESSION SUMMARY — compressed for handoff]\n" + llm_text
            )

    if len(summary) > HANDOFF_MAX_SUMMARY_CHARS:
        summary = summary[: HANDOFF_MAX_SUMMARY_CHARS - 20] + "\n… [truncated]"

    cloud_prompt = build_cloud_handoff_prompt(
        summary_markdown=summary,
        user_text=user_ask,
        local_attempt=local_attempt,
        web_block=web_block,
    )
    return cloud_prompt, {
        "compressed": True,
        "raw_chars": raw_chars,
        "compressed_chars": len(summary),
        "cloud_prompt_chars": len(cloud_prompt),
        "summarize_provider": provider,
    }


def _extract_session_summary(text: str) -> str:
    lowered = (text or "").lower()
    marker = SESSION_SUMMARY_MARKER.lower()
    idx = lowered.find(marker)
    if idx < 0:
        return ""
    chunk = text[idx:]
    for stop in ("<<<FILE", "[USER REQUEST]", "\n---\nUse this research"):
        j = chunk.find(stop)
        if j > 0:
            chunk = chunk[:j]
    return chunk.strip()[:HANDOFF_MAX_SUMMARY_CHARS]


def append_prior_provider_block(base_prompt: str, provider: str, detail: str) -> str:
    """Append a prior-provider failure appendix for the next cloud provider."""
    return (
        f"{base_prompt.rstrip()}\n\n"
        f"[PRIOR ESCALATION ATTEMPT — {provider}]\n"
        "The user already tried the provider below. Continue from the session summary; do not restart.\n"
        f"{detail[:3000]}"
    )
