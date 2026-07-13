"""
OpenAI-compatible chat router with local-first intelligence.

Flow:
  casual   -> persona llama-server
              (+ optional web search → web_knowledge Chroma when triggered)
  coding   -> hot-swap to local coder (+ coding_lessons + web_knowledge RAG)
              -> live web search (DuckDuckGo/Brave/Serper/Bing) when enabled
              -> Claude/Gemini only if local coder fails (CLOUD_FALLBACK_ORDER)
              -> learn useful answers into coding_lessons / web_knowledge
              -> hot-swap back to persona for voice rewrite
  japanese -> persona first; cloud last resort for raw facts, then voice

Progress / "thoughts":
  When stream=true, emits SSE events so Blossom (or any client) can show a live trail:
    data: {"object":"blossom.thought","step":"...","message":"..."}
    data: {"object":"chat.completion.chunk","choices":[{"delta":{"content":"..."}}]}
    data: [DONE]
  When stream=false, returns normal completion JSON plus blossom_thoughts[].
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from queue import Queue
from typing import Any, Callable

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
# Project .env wins over stale shell / User env (e.g. old CHAT_ROUTER_HOST).
load_dotenv(SCRIPT_DIR / ".env", override=True)
load_dotenv(PROJECT_ROOT / ".env", override=True)

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from openai import OpenAI

from LlamaServerManager import CODER_MODEL, PERSONA_CTX, server_manager
from EditorContext import (
    build_task_brief,
    extract_user_request as _extract_user_request,
    looks_like_editor_dump,
    pack_editor_context,
    parse_editor_files,
)
from MemoryUpdater import (
    CONVERSATIONAL_MODEL,
    LLAMA_SERVER_URL,
    CompanionEngine,
)
from SemanticMemory import (
    COLLECTION_CODING,
    COLLECTION_WEB,
    format_memories_for_prompt,
    learn_coding_lesson,
    learn_web_findings,
    query_memories,
)
from WebSearch import (
    WEB_SEARCH_ENABLED,
    WEB_SEARCH_PROVIDER,
    format_search_results_for_prompt,
    should_search,
    web_search,
)
from VoiceClient import (
    SPEAK_EMOTIONS,
    VOICE_DEFER_STREAM,
    VOICE_ENABLED,
    VOICE_SERVICE_URL,
    language_system_nudge,
    list_voice_packs,
    maybe_attach_voice,
    normalize_locale,
    resolve_audio_path,
    synthesize_and_attach,
    voice_service_healthy,
    voice_system_nudge,
)

logging.basicConfig(level=logging.INFO, format="[Blossom]: %(message)s")
logger = logging.getLogger(__name__)

ROUTER_HOST = os.getenv("CHAT_ROUTER_HOST", "127.0.0.1")
ROUTER_PORT = int(os.getenv("CHAT_ROUTER_PORT", "8081"))

LOCAL_VOICE_MODEL = os.getenv("LOCAL_VOICE_MODEL", CONVERSATIONAL_MODEL.name)
LOCAL_CODER_MODEL = os.getenv("LOCAL_CODER_MODEL", CODER_MODEL.name)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", os.getenv("CLOUD_INTEL_MODEL", "gemini-2.5-flash-lite"))
CLAUDE_API_KEY = (
    os.getenv("CLAUDE_API_KEY", "").strip()
    or os.getenv("ANTHROPIC_API_KEY", "").strip()
)
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
CLOUD_FALLBACK_ORDER = [
    part.strip().lower()
    for part in os.getenv("CLOUD_FALLBACK_ORDER", "claude,gemini").split(",")
    if part.strip()
]
# Master switch: when false, coding never calls Claude/Gemini (local only).
CLOUD_FALLBACK_ENABLED = os.getenv("CLOUD_FALLBACK_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# When false, keep a "good enough" local answer even if multi-file heuristics look incomplete.
# Default false — incomplete→cloud was burning Claude credits on simple delete/edit tasks.
CLOUD_ESCALATE_ON_INCOMPLETE = os.getenv(
    "CLOUD_ESCALATE_ON_INCOMPLETE", "false"
).strip().lower() in {"1", "true", "yes", "on"}
# When false, ignore ESCALATE_CLOUD / ESCALATE_GEMINI markers from the local coder.
CLOUD_ESCALATE_ON_REQUEST = os.getenv(
    "CLOUD_ESCALATE_ON_REQUEST", "true"
).strip().lower() in {"1", "true", "yes", "on"}

LOCAL_CLIENT = OpenAI(base_url=f"{LLAMA_SERVER_URL}/v1", api_key="local")

_CODING_RULES_PATH = Path(__file__).resolve().parent / "coding_rules.txt"


def _load_coding_rules() -> str:
    try:
        text = _CODING_RULES_PATH.read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError as exc:
        logger.warning("Could not read coding_rules.txt: %s", exc)
    return (
        "CREATE = new path in its own fence. EDIT = minimal change; preserve originals. "
        "Never overwrite an attached file with a different new file's contents. "
        "One fence per file, labeled with path=..."
    )


CODING_RULES = _load_coding_rules()  # boot-time cache; prompts also reload from disk


def _coding_rules_text() -> str:
    """Prefer fresh coding_rules.txt so edits apply after ChatRouter restart (or same process)."""
    return _load_coding_rules() or CODING_RULES

GEMINI_CLIENT = None
if GEMINI_API_KEY:
    GEMINI_CLIENT = OpenAI(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key=GEMINI_API_KEY,
    )

CLAUDE_CLIENT = None
if CLAUDE_API_KEY:
    try:
        from anthropic import Anthropic

        CLAUDE_CLIENT = Anthropic(api_key=CLAUDE_API_KEY)
    except ImportError:
        logger.warning(
            "anthropic package not installed; Claude fallback disabled. "
            "Run: pip install anthropic"
        )

CLOUD_CLIENT = GEMINI_CLIENT or CLAUDE_CLIENT
CLOUD_INTEL_MODEL = GEMINI_MODEL

CODING_KEYWORDS = (
    "write a function",
    "bug",
    "error",
    "fix",
    "code",
    "compile",
    "script",
    "stackoverflow",
    "traceback",
    "typescript",
    "javascript",
    "python",
    "refactor",
)
JAPANESE_KEYWORDS = (
    "how do i say",
    "japanese",
    "translate",
    "kanji",
    "jlpt",
    "grammar",
    "hiragana",
    "katakana",
)

ProgressFn = Callable[[dict[str, Any]], None]

swap_lock = threading.Lock()
engine = CompanionEngine()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chatrouter")

# Leave room for the persona completion itself inside the loaded ctx window.
PERSONA_PROMPT_BUDGET = max(2048, PERSONA_CTX - int(os.getenv("PERSONA_REPLY_RESERVE", "1536")))


def _approx_tokens(text: str) -> int:
    """Rough token estimate (chars/4). Good enough for ctx budgeting."""
    return max(1, (len(text or "") + 3) // 4)


def _synthetic_completion(content: str) -> dict:
    return {
        "id": f"chatcmpl-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": LOCAL_VOICE_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Bootstrapping persona llama-server...")
    with swap_lock:
        server_manager.ensure("persona")
    # Compactor needs :11434 — must run after llama is up (not before ChatRouter in start-server.ps1).
    compact_on_boot = os.getenv("COMPACT_ON_STARTUP", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if compact_on_boot:
        try:
            from HistoryCompactor import compact_and_summarize_history

            logger.info("Running history compaction (llama ready)…")
            await asyncio.get_running_loop().run_in_executor(
                _executor, compact_and_summarize_history
            )
        except Exception:
            logger.exception("History compaction skipped")
    try:
        yield
    finally:
        logger.info("Shutting down llama-server...")
        with swap_lock:
            server_manager.stop()
        _executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Blossom Chat Router", lifespan=lifespan)

# Local companion UI (Nuxt on :3000). Direct browser calls + CORS preflights.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def is_coding_request(user_prompt: str) -> bool:
    text = (user_prompt or "").lower()
    if looks_like_editor_dump(user_prompt):
        return True
    return any(kw in text for kw in CODING_KEYWORDS) or "```" in (user_prompt or "")


def is_japanese_request(user_prompt: str) -> bool:
    text = (user_prompt or "").lower()
    return any(kw in text for kw in JAPANESE_KEYWORDS)


def _message_text(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "") or ""
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts).strip()
    return str(content).strip()


def _reasoning_text(message: Any) -> str:
    """Qwen3 / thinking models expose chain-of-thought here (llama-server OpenAI API)."""
    if isinstance(message, dict):
        raw = message.get("reasoning_content", "")
    else:
        raw = getattr(message, "reasoning_content", "") or ""
    return str(raw or "").strip()


def _emit_model_reasoning(
    on_progress: ProgressFn | None,
    message: Any,
    *,
    source: str = "local",
) -> None:
    reasoning = _reasoning_text(message)
    if not reasoning:
        return
    _think(
        on_progress,
        "model_reasoning",
        reasoning,
        source=source,
        label=_label_intel_source(source),
    )


def _think(on_progress: ProgressFn | None, step: str, message: str, **extra: Any) -> dict:
    event = {
        "object": "blossom.thought",
        "step": step,
        "message": message,
        "ts": time.time(),
        **extra,
    }
    logger.info("thought step=%s %s", step, message)
    if on_progress:
        on_progress(event)
    return event


def _maybe_language_nudge(messages: list[dict], locale: str) -> list[dict]:
    messages.append({"role": "system", "content": language_system_nudge(locale)})
    return messages


def _maybe_voice_nudge(messages: list[dict], locale: str = "ja") -> list[dict]:
    """When voice is on, steer wording for TTS (language-aware)."""
    if not VOICE_ENABLED:
        return messages
    messages.append({"role": "system", "content": voice_system_nudge(locale)})
    return messages


def _apply_chat_mode_nudges(messages: list[dict], locale: str) -> list[dict]:
    _maybe_language_nudge(messages, locale)
    _maybe_voice_nudge(messages, locale)
    return messages


def _local_completion(messages: list[dict], temperature: float = 0.82) -> dict:
    response = LOCAL_CLIENT.chat.completions.create(
        model=LOCAL_VOICE_MODEL,
        messages=messages,
        temperature=temperature,
        stream=False,
    )
    return response.model_dump()


def _local_completion_with_reasoning(
    messages: list[dict],
    *,
    temperature: float = 0.82,
    on_progress: ProgressFn | None = None,
    source: str = "persona",
) -> dict:
    final_response = _local_completion(messages, temperature=temperature)
    _emit_model_reasoning(
        on_progress,
        final_response["choices"][0]["message"],
        source=source,
    )
    return final_response


def _cloud_system_prompt(purpose: str = "general") -> str:
    if purpose == "coding":
        return (
            "You are a senior software engineer. Provide a correct, concise solution "
            "with code blocks when needed. No filler.\n\n"
            + _coding_rules_text()
        )
    return (
        "Provide only objective facts, corrections, or raw code blocks. "
        "Be completely concise with zero conversational filler."
    )


def _coder_system_prompt() -> str:
    return (
        "You are Blossom's local coding engine. Complete multi-step software tasks "
        "reliably by planning, acting in small steps, and verifying.\n\n"
        + _coding_rules_text()
    )


def _local_answer_requests_escalate(answer: str) -> bool:
    text = (answer or "").upper()
    return "ESCALATE_CLOUD" in text or "ESCALATE_GEMINI" in text


def _coding_answer_looks_incomplete(user_prompt: str, answer: str) -> bool:
    """
    Heuristic: multi-file CREATE+EDIT asks should produce multiple path-labeled fences.
    Used to fall through to cloud when local clearly collapsed files.
    Never fires for simple delete/remove-only asks.
    """
    focus = _extract_user_request(user_prompt).lower()
    ans = answer or ""

    # Simple delete/remove: local DELETE markers are enough — do not escalate to cloud.
    delete_only = bool(
        re.search(r"\b(delete|remove)\b", focus)
        and not re.search(
            r"\b(create|generate|new file|add a (?:page|link)|megaman|about\.html)\b",
            focus,
        )
    )
    if delete_only:
        return False

    create_words = any(
        w in focus
        for w in (
            "create",
            "generate",
            "new file",
            "make a",
            "add a page",
            "about.html",
        )
    )
    edit_words = any(
        w in focus
        for w in ("index.html", "add a link", "keep the original", "edit", "update")
    )
    if not (create_words and edit_words):
        return False

    # Need at least two code fences (open+close each → 4 backticks groups minimum)
    if ans.count("```") < 4:
        return True

    # about.html create+edit: require a fence info-string mentioning about.html
    if "about.html" in focus and not re.search(
        r"```[^\n]*about\.html", ans, flags=re.I
    ):
        return True

    # Prefer explicit path= labels when multiple files are involved
    path_labels = len(re.findall(r"```[^\n]*\b(?:path|file)\s*=", ans, flags=re.I))
    if path_labels < 2 and ans.count("```") < 6:
        # two fences without path labels still ok if both filenames appear in info lines
        info_hits = len(
            re.findall(r"```[^\n]*(?:index\.html|about\.html)", ans, flags=re.I)
        )
        if info_hits < 2:
            return True
    return False


def _gemini_facts(user_prompt: str, purpose: str = "general") -> str:
    if GEMINI_CLIENT is None:
        raise RuntimeError("GEMINI_API_KEY is not set")
    response = GEMINI_CLIENT.chat.completions.create(
        model=GEMINI_MODEL,
        messages=[
            {"role": "system", "content": _cloud_system_prompt(purpose)},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    return _message_text(response.choices[0].message)


def _claude_facts(user_prompt: str, purpose: str = "general") -> str:
    if CLAUDE_CLIENT is None:
        raise RuntimeError("CLAUDE_API_KEY / ANTHROPIC_API_KEY is not set")
    response = CLAUDE_CLIENT.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=_cloud_system_prompt(purpose),
        messages=[{"role": "user", "content": user_prompt}],
        temperature=0.2,
    )
    parts = []
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _cloud_facts(
    user_prompt: str,
    purpose: str = "general",
    on_progress: ProgressFn | None = None,
) -> tuple[str, str]:
    errors: list[str] = []
    for provider in CLOUD_FALLBACK_ORDER:
        try:
            if provider == "claude":
                if CLAUDE_CLIENT is None:
                    errors.append("claude: not configured")
                    continue
                _think(on_progress, "cloud", f"Asking Claude ({CLAUDE_MODEL})…", provider="claude")
                return _claude_facts(user_prompt, purpose=purpose), "claude"
            if provider in {"gemini", "google"}:
                if GEMINI_CLIENT is None:
                    errors.append("gemini: not configured")
                    continue
                _think(on_progress, "cloud", f"Asking Gemini ({GEMINI_MODEL})…", provider="gemini")
                return _gemini_facts(user_prompt, purpose=purpose), "gemini"
            errors.append(f"{provider}: unknown provider")
        except Exception as exc:
            logger.warning("Cloud provider %s failed: %s", provider, exc)
            _think(
                on_progress,
                "cloud_error",
                f"{provider} failed: {exc}",
                provider=provider,
            )
            errors.append(f"{provider}: {exc}")

    detail = (
        "Local intelligence failed and no cloud fallback succeeded. "
        + ("; ".join(errors) if errors else "Set CLAUDE_API_KEY and/or GEMINI_API_KEY.")
    )
    raise HTTPException(status_code=503, detail=detail)


def _gather_web_context(
    user_prompt: str,
    *,
    coding: bool = False,
    on_progress: ProgressFn | None = None,
) -> str:
    """Retrieve prior web_knowledge and optionally run a live search + learn."""
    blocks: list[str] = []
    focus = _extract_user_request(user_prompt)

    _think(on_progress, "web_memory", "Checking prior web knowledge…")
    prior = query_memories(focus, collection=COLLECTION_WEB)
    if prior:
        blocks.append(
            format_memories_for_prompt(
                prior,
                heading="[PRIOR WEB KNOWLEDGE — from earlier searches]",
            )
        )
        _think(
            on_progress,
            "web_memory",
            f"Loaded {len(prior)} prior web memory(ies).",
            count=len(prior),
        )

    if not should_search(user_prompt, coding=coding):
        return "\n\n".join(blocks)

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
        return "\n\n".join(blocks)

    if not results:
        _think(on_progress, "web_search", "No web results.")
        return "\n\n".join(blocks)

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
    blocks.append(format_search_results_for_prompt(results))
    return "\n\n".join(blocks)


def _local_coder_answer(
    user_prompt: str,
    on_progress: ProgressFn | None = None,
    web_block: str = "",
) -> str:
    packed_prompt, pack_stats = pack_editor_context(user_prompt)
    if pack_stats.get("packed"):
        _think(
            on_progress,
            "editor_pack",
            (
                f"Packed editor context: {pack_stats.get('files_in', 0)} file(s) in → "
                f"{pack_stats.get('files_kept', 0)} kept, "
                f"{pack_stats.get('chunks_kept', 0)} chunk(s), "
                f"~{pack_stats.get('approx_tokens')} tokens "
                f"(budget {pack_stats.get('budget')})."
            ),
            **{k: v for k, v in pack_stats.items() if k != "ask"},
        )

    focus = _extract_user_request(user_prompt)
    attached = [f.path for f in parse_editor_files(user_prompt)]
    task_brief = build_task_brief(focus, attached)
    if task_brief:
        _think(on_progress, "task_brief", "Added create/edit task brief for the coder.")

    _think(on_progress, "coding_lessons", "Retrieving coding lessons from memory…")
    lessons = query_memories(focus, collection=COLLECTION_CODING)
    lesson_block = format_memories_for_prompt(
        lessons, heading="[PRIOR CODING LESSONS — prefer these patterns when relevant]"
    )
    if lessons:
        _think(
            on_progress,
            "coding_lessons",
            f"Loaded {len(lessons)} relevant coding lesson(s).",
            count=len(lessons),
        )
    messages = [
        {"role": "system", "content": _coder_system_prompt()},
        {"role": "system", "content": task_brief},
    ]
    if lesson_block:
        messages.append({"role": "system", "content": lesson_block})
    if web_block:
        messages.append({"role": "system", "content": web_block})
    messages.append({"role": "user", "content": packed_prompt})

    _think(on_progress, "coder_infer", "Running local coder model…")
    response = LOCAL_CLIENT.chat.completions.create(
        model=LOCAL_CODER_MODEL,
        messages=messages,
        temperature=0.2,
        stream=False,
    )
    msg = response.choices[0].message
    _emit_model_reasoning(on_progress, msg, source="local_coder")
    return _message_text(msg)


def _get_coding_intel(
    user_prompt: str,
    on_progress: ProgressFn | None = None,
) -> tuple[str, str]:
    web_block = _gather_web_context(user_prompt, coding=True, on_progress=on_progress)
    packed_prompt, _pack_stats = pack_editor_context(user_prompt)
    enriched = packed_prompt
    if web_block:
        enriched = (
            f"{packed_prompt}\n\n---\nUse this research context when helpful:\n{web_block}"
        )

    answer = ""
    if server_manager.coder_available():
        try:
            _think(on_progress, "swap_coder", f"Loading coder GGUF ({CODER_MODEL.name})…")
            server_manager.ensure("coder")
            _think(on_progress, "swap_coder", "Coder model ready.")
            answer = _local_coder_answer(
                user_prompt, on_progress=on_progress, web_block=web_block
            )
            if answer and len(answer.strip()) >= 20:
                wants_escalate = _local_answer_requests_escalate(answer)
                looks_incomplete = _coding_answer_looks_incomplete(user_prompt, answer)
                if wants_escalate and CLOUD_FALLBACK_ENABLED and CLOUD_ESCALATE_ON_REQUEST:
                    _think(
                        on_progress,
                        "escalate",
                        "Local coder requested cloud escalation; trying cloud…",
                    )
                elif (
                    looks_incomplete
                    and CLOUD_FALLBACK_ENABLED
                    and CLOUD_ESCALATE_ON_INCOMPLETE
                ):
                    _think(
                        on_progress,
                        "escalate",
                        "Local coder answer looks incomplete for multi-file create/edit; trying cloud…",
                    )
                else:
                    if wants_escalate and not (
                        CLOUD_FALLBACK_ENABLED and CLOUD_ESCALATE_ON_REQUEST
                    ):
                        _think(
                            on_progress,
                            "escalate_skipped",
                            "Local coder asked to escalate; cloud disabled — keeping local answer.",
                        )
                    elif looks_incomplete and not (
                        CLOUD_FALLBACK_ENABLED and CLOUD_ESCALATE_ON_INCOMPLETE
                    ):
                        _think(
                            on_progress,
                            "escalate_skipped",
                            "Local answer may be incomplete; cloud escalate-on-incomplete is off — keeping local.",
                        )
                    _think(on_progress, "learn", "Saving local coder answer into coding_lessons…")
                    learn_coding_lesson(
                        _extract_user_request(user_prompt),
                        answer,
                        source="local_coder",
                    )
                    return answer, "local_coder"
            else:
                _think(on_progress, "fallback", "Local coder answer was weak; trying cloud…")
        except Exception as exc:
            logger.warning("Local coder failed (%s); falling back to cloud.", exc)
            _think(on_progress, "fallback", f"Local coder failed ({exc}); trying cloud…")
    else:
        _think(
            on_progress,
            "fallback",
            f"Coder GGUF missing ({CODER_MODEL.name}); using cloud…",
        )

    if not CLOUD_FALLBACK_ENABLED:
        _think(
            on_progress,
            "fallback",
            "Cloud fallback disabled (CLOUD_FALLBACK_ENABLED=false); returning best local answer.",
        )
        if answer and len(answer.strip()) >= 20:
            return answer, "local_coder"
        raise HTTPException(
            status_code=503,
            detail=(
                "Local coder unavailable/weak and CLOUD_FALLBACK_ENABLED=false. "
                "Enable cloud or fix the coder GGUF."
            ),
        )

    answer, provider = _cloud_facts(
        enriched, purpose="coding", on_progress=on_progress
    )
    _think(on_progress, "learn", f"Saving {provider} answer into coding_lessons…")
    learn_coding_lesson(_extract_user_request(user_prompt), answer, source=provider)
    return answer, provider


def _persona_wrap(
    user_prompt: str,
    raw_facts: str,
    kind: str,
    on_progress: ProgressFn | None = None,
    *,
    locale: str = "ja",
) -> dict:
    focus = _extract_user_request(user_prompt)
    facts_tokens = _approx_tokens(raw_facts)
    # Large coding payloads (full HTML/files) won't fit history+persona+rewrite in one ctx.
    if kind == "coding" and facts_tokens > int(PERSONA_PROMPT_BUDGET * 0.6):
        log_text = focus if len(user_prompt) > 4000 else user_prompt
        engine._log_message("user", log_text)
        _think(
            on_progress,
            "persona_skip",
            (
                f"Coder answer ~{facts_tokens} tokens exceeds persona wrap budget "
                f"({PERSONA_PROMPT_BUDGET}); returning technical answer as-is."
            ),
            facts_tokens=facts_tokens,
            budget=PERSONA_PROMPT_BUDGET,
        )
        server_manager.ensure("persona")  # leave persona loaded for next casual turn
        return _synthetic_completion(raw_facts)

    _think(on_progress, "swap_persona", "Loading persona model for voice rewrite…")
    server_manager.ensure("persona")
    _think(on_progress, "persona", "Rewriting answer in companion voice…")

    if kind == "coding":
        # Slim prompt: do NOT re-inject editor file dumps or long chat history.
        log_text = focus if len(user_prompt) > 4000 else user_prompt
        engine._log_message("user", log_text)
        instruction = (
            "The user asked a technical/coding question. Below is the exact technical answer "
            "from the coding engine.\n\n"
            "Rewrite it in your natural companion voice with these constraints:\n"
            "- Keep the PLAN / VERIFY notes short if present; do not invent new plans.\n"
            "- Lead with the files/fix, not a cute monologue.\n"
            "- Keep EVERY markdown code fence exactly as given (same path= labels, same contents).\n"
            "- If there are multiple fences (e.g. index.html + about.html), keep all of them.\n"
            "- Do not merge a new file into an existing file.\n"
            "- No stock metaphors, no emoji spam, no P.S. gimmicks.\n"
            "- One short personality beat is enough; usefulness first.\n\n"
            f"USER ASK:\n{focus}\n\n"
            f"TECHNICAL ANSWER:\n{raw_facts}"
        )
        persona_messages = [
            {
                "role": "system",
                "content": (
                    "You are a warm, precise companion helping with coding. "
                    "Preserve every code fence and path label exactly. Never collapse "
                    "multiple files into one."
                ),
            },
            {"role": "user", "content": instruction},
        ]
        temperature = 0.55
    else:
        persona_messages = engine.build_chat_messages(user_prompt, history_limit=8)
        _apply_chat_mode_nudges(persona_messages, locale)
        instruction = (
            "Rewrite the following facts in your natural companion voice. Stay accurate, "
            "avoid canned jokes and emoji spam, and don't sound like a scripted mascot.\n\n"
            f"FACTS:\n{raw_facts}"
        )
        persona_messages.append({"role": "user", "content": instruction})
        temperature = 0.7

    prompt_tokens = sum(_approx_tokens(m.get("content", "")) for m in persona_messages)
    if prompt_tokens > PERSONA_PROMPT_BUDGET:
        _think(
            on_progress,
            "persona_skip",
            (
                f"Persona wrap prompt ~{prompt_tokens} tokens over budget "
                f"{PERSONA_PROMPT_BUDGET}; returning technical answer as-is."
            ),
            prompt_tokens=prompt_tokens,
            budget=PERSONA_PROMPT_BUDGET,
        )
        return _synthetic_completion(raw_facts)

    final_response = _local_completion(persona_messages, temperature=temperature)
    _emit_model_reasoning(
        on_progress,
        final_response["choices"][0]["message"],
        source="persona",
    )
    return final_response


def _label_intel_source(source: str | None) -> str:
    if not source:
        return "Unknown"
    key = source.strip().lower()
    labels = {
        "local_coder": "Local coder",
        "local": "Local coder",
        "coder": "Local coder",
        "persona": "Local persona",
        "claude": "Claude",
        "gemini": "Gemini",
        "google": "Gemini",
    }
    if key in labels:
        return labels[key]
    if key.startswith("claude"):
        return "Claude"
    return source


def _finalize_response(
    final_response: dict,
    thoughts: list[dict],
    *,
    intel_source: str | None = None,
) -> dict:
    assistant_text = ""
    try:
        assistant_text = _message_text(final_response["choices"][0]["message"])
    except Exception:
        assistant_text = ""
    if assistant_text:
        cleaned = engine.break_reply_echo(assistant_text)
        if cleaned != assistant_text:
            logger.info("Anti-echo post-pass trimmed sticky opener/closer.")
            assistant_text = cleaned
            try:
                final_response["choices"][0]["message"]["content"] = assistant_text
            except Exception:
                pass
        engine._log_message("assistant", assistant_text)

    final_response.setdefault("object", "chat.completion")
    final_response.setdefault("created", int(time.time()))
    final_response.setdefault("model", LOCAL_VOICE_MODEL)
    final_response["blossom_thoughts"] = thoughts
    if intel_source:
        final_response["blossom_intel_source"] = intel_source
        final_response["blossom_intel_label"] = _label_intel_source(intel_source)
    return final_response


def _active_voice_id() -> str | None:
    """Persona voice_id → Voice/characters/<id>/ pack; None lets the voice service use default."""
    try:
        persona = engine.get_persona()
        vid = str(persona.get("voice_id") or "").strip()
        return vid or None
    except Exception:
        return None


def run_chat_pipeline(
    last_user_message: str,
    on_progress: ProgressFn | None = None,
    *,
    defer_voice: bool | None = None,
    locale: str = "ja",
    voice_id: str | None = None,
) -> tuple[dict, str | None]:
    """Synchronous pipeline used by both streaming and non-streaming endpoints.

    Returns (final_response, pending_speak_text). When defer_voice is True and
    TTS is needed, pending_speak_text is set so the caller can synthesize after
    streaming text to the client.
    """
    if defer_voice is None:
        defer_voice = VOICE_DEFER_STREAM
    locale = normalize_locale(locale)
    if voice_id is None:
        voice_id = _active_voice_id()
    else:
        voice_id = str(voice_id).strip() or None


    thoughts: list[dict] = []
    intel_source: str | None = None

    def progress(event: dict) -> None:
        thoughts.append(event)
        if on_progress:
            on_progress(event)

    coding = is_coding_request(last_user_message)
    japanese = is_japanese_request(last_user_message)

    with swap_lock:
        if coding:
            _think(progress, "route", "Detected coding request.")
            raw_facts, source = _get_coding_intel(
                last_user_message, on_progress=progress
            )
            intel_source = source
            _think(
                progress,
                "intel_ready",
                f"Coding intel ready (source={source}).",
                source=source,
                label=_label_intel_source(source),
            )
            final_response = _persona_wrap(
                last_user_message,
                raw_facts,
                kind="coding",
                on_progress=progress,
                locale=locale,
            )
        elif japanese:
            _think(progress, "route", "Detected Japanese-study request.")
            _think(progress, "swap_persona", "Ensuring persona model is loaded…")
            server_manager.ensure("persona")
            persona_messages = engine.build_chat_messages(last_user_message)
            _apply_chat_mode_nudges(persona_messages, locale)
            intel_source = "persona"
            try:
                _think(progress, "persona", "Answering with local persona…")
                final_response = _local_completion_with_reasoning(
                    persona_messages,
                    temperature=0.82,
                    on_progress=progress,
                    source="persona",
                )
                local_text = _message_text(final_response["choices"][0]["message"])
                if len(local_text) < 20 and (GEMINI_CLIENT or CLAUDE_CLIENT):
                    _think(progress, "fallback", "Local answer was thin; enriching via cloud…")
                    raw_facts, provider = _cloud_facts(
                        last_user_message, purpose="general", on_progress=progress
                    )
                    intel_source = provider
                    persona_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Augment/correct using these concise facts, staying in character:\n\n"
                                f"{raw_facts}"
                            ),
                        }
                    )
                    _think(progress, "persona", f"Rewriting with {provider} facts…")
                    final_response = _local_completion_with_reasoning(
                        persona_messages,
                        temperature=0.82,
                        on_progress=progress,
                        source="persona",
                    )
            except Exception as exc:
                _think(progress, "fallback", f"Japanese local path failed ({exc}); cloud last resort.")
                raw_facts, provider = _cloud_facts(
                    last_user_message, purpose="general", on_progress=progress
                )
                intel_source = provider
                persona_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Use these facts and answer in character:\n\n"
                            f"{raw_facts}"
                        ),
                    }
                )
                _think(progress, "persona", f"Rewriting with {provider} facts…")
                final_response = _local_completion_with_reasoning(
                    persona_messages,
                    temperature=0.82,
                    on_progress=progress,
                    source="persona",
                )
        else:
            _think(progress, "route", "Casual chat → persona model.")
            _think(progress, "swap_persona", "Ensuring persona model is loaded…")
            server_manager.ensure("persona")
            intel_source = "persona"
            persona_messages = engine.build_chat_messages(last_user_message)
            _apply_chat_mode_nudges(persona_messages, locale)
            web_block = _gather_web_context(
                last_user_message, coding=False, on_progress=progress
            )
            if web_block:
                persona_messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Optional research context. Use only what helps answer the user; "
                            "do not dump URLs unless asked.\n\n" + web_block
                        ),
                    }
                )
            _think(progress, "persona", "Generating companion reply…")
            final_response = _local_completion_with_reasoning(
                persona_messages,
                temperature=0.7,
                on_progress=progress,
                source="persona",
            )

    _think(progress, "done", "Pipeline finished.", source=intel_source or "unknown")
    # One-shot rewrite if the draft is a near-copy of a recent assistant reply
    # (classic small-model habit: swap one noun into an old template).
    try:
        draft = _message_text(final_response["choices"][0]["message"])
    except Exception:
        draft = ""
    if draft and engine.reply_looks_like_remix(draft):
        _think(
            progress,
            "anti_echo",
            "Draft remixed an older reply — rewriting fresh…",
        )
        try:
            repair = _local_completion_with_reasoning(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are rewriting a bad companion draft. The draft recycled an older "
                            "reply (same structure/phrases with a noun swap). Write a COMPLETELY "
                            "NEW in-character reply that answers the user's latest message. "
                            "Do not reuse the draft's sentences, closings, or template. "
                            "Reply with only the new message text."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"User's latest message:\n{last_user_message}\n\n"
                            f"Bad draft (do not reuse):\n{draft}\n\n"
                            "Fresh reply:"
                        ),
                    },
                ],
                temperature=0.9,
                on_progress=progress,
                source="persona",
            )
            repaired = _message_text(repair["choices"][0]["message"]).strip()
            if repaired and not engine.reply_looks_like_remix(repaired, threshold=0.58):
                final_response = repair
            elif repaired and len(repaired) > 20:
                # Prefer any coherent rewrite over an obvious template remix.
                final_response = repair
        except Exception:
            logger.exception("Anti-echo rewrite failed; keeping original draft")

    final_response = _finalize_response(
        final_response, thoughts, intel_source=intel_source
    )
    if VOICE_ENABLED and not coding and not defer_voice:
        # Sync path may still use LLM emotion mode; ensure persona is loaded.
        try:
            server_manager.ensure("persona")
        except Exception:
            logger.exception("Could not ensure persona for voice emotion classify")
    final_response, pending_speak = maybe_attach_voice(
        final_response,
        skip_voice=coding,
        complete_fn=_local_completion,
        message_text_fn=_message_text,
        on_progress=progress,
        defer_speak=bool(defer_voice and VOICE_ENABLED and not coding),
        locale=locale,
        voice_id=voice_id,
    )
    return final_response, pending_speak


def _openai_content_chunk(text: str, chunk_id: str) -> dict:
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": LOCAL_VOICE_MODEL,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": text},
                "finish_reason": None,
            }
        ],
    }


def _openai_stop_chunk(chunk_id: str) -> dict:
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": LOCAL_VOICE_MODEL,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }


@app.get("/health")
async def health():
    return {
        "ok": True,
        "local": LLAMA_SERVER_URL,
        "active_role": server_manager.current_role,
        "coder_available": server_manager.coder_available(),
        "cloud_enabled": bool(GEMINI_CLIENT or CLAUDE_CLIENT) and CLOUD_FALLBACK_ENABLED,
        "cloud_providers": {
            "claude": CLAUDE_CLIENT is not None,
            "gemini": GEMINI_CLIENT is not None,
            "order": CLOUD_FALLBACK_ORDER,
            "fallback_enabled": CLOUD_FALLBACK_ENABLED,
            "escalate_on_incomplete": CLOUD_ESCALATE_ON_INCOMPLETE,
            "escalate_on_request": CLOUD_ESCALATE_ON_REQUEST,
        },
        "model_voice": LOCAL_VOICE_MODEL,
        "model_coder": LOCAL_CODER_MODEL,
        "model_claude": CLAUDE_MODEL,
        "model_gemini": GEMINI_MODEL,
        "web_search": {
            "enabled": WEB_SEARCH_ENABLED,
            "provider": WEB_SEARCH_PROVIDER,
        },
        "supports_thoughts": True,
        "supports_memory_write": True,
        "supports_persona": True,
        "supports_voice": VOICE_ENABLED,
        "voice": {
            "enabled": VOICE_ENABLED,
            "service_url": VOICE_SERVICE_URL if VOICE_ENABLED else None,
            "service_ok": voice_service_healthy() if VOICE_ENABLED else False,
        },
    }


@app.get("/v1/voices")
async def get_voices():
    """List discovered Voice/characters/<id> packs (proxied from the voice service)."""
    if not VOICE_ENABLED:
        return {"ok": False, "voices": [], "default_voice": None, "enabled": False}
    body = await asyncio.get_running_loop().run_in_executor(_executor, list_voice_packs)
    body = dict(body) if isinstance(body, dict) else {}
    body.setdefault("ok", False)
    body.setdefault("voices", [])
    body["enabled"] = True
    return body


@app.get("/v1/audio/{audio_id}")
async def get_audio(audio_id: str):
    """Serve a cached WAV synthesized for an assistant reply."""
    path = resolve_audio_path(audio_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(
        path,
        media_type="audio/wav",
        filename=f"{audio_id}.wav",
    )


@app.get("/v1/persona")
async def get_persona():
    """Active companion personality + catalog of all slots."""
    try:
        bundle = engine.get_persona_bundle()
        return {"ok": True, **bundle}
    except Exception as exc:
        logger.exception("Failed to load persona")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put("/v1/persona")
async def put_persona(request: Request):
    """Update a personality slot (defaults to the active one)."""
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    patch = body.get("persona") if isinstance(body.get("persona"), dict) else body
    if not isinstance(patch, dict):
        raise HTTPException(status_code=400, detail="Expected persona object")
    persona_id = body.get("id") or patch.get("id")

    try:
        persona = await asyncio.get_running_loop().run_in_executor(
            _executor,
            lambda: engine.update_persona(patch, persona_id=persona_id),
        )
        bundle = engine.get_persona_bundle()
        return {"ok": True, "persona": persona, **{k: bundle[k] for k in ("active_id", "personas")}}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to save persona")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/v1/personas")
async def list_personas():
    try:
        return {"ok": True, "personas": engine.list_personas(), "active_id": engine.get_persona_bundle()["active_id"]}
    except Exception as exc:
        logger.exception("Failed to list personas")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/personas")
async def create_persona(request: Request):
    """
    Create a new personality slot.
    Body: { "companion_name": str, "copy_from_active": bool, "activate": bool }
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = str((body or {}).get("companion_name") or "New companion").strip()
    copy_from = bool((body or {}).get("copy_from_active"))
    activate = bool((body or {}).get("activate"))

    def _create():
        created = engine.create_persona(
            companion_name=name, copy_from_active=copy_from
        )
        if activate:
            return engine.activate_persona(created["id"])
        return engine.get_persona_bundle()

    try:
        bundle = await asyncio.get_running_loop().run_in_executor(_executor, _create)
        return {"ok": True, **bundle}
    except Exception as exc:
        logger.exception("Failed to create persona")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/personas/{persona_id}/activate")
async def activate_persona(persona_id: str):
    try:
        bundle = await asyncio.get_running_loop().run_in_executor(
            _executor, lambda: engine.activate_persona(persona_id)
        )
        return {"ok": True, **bundle}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to activate persona")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/v1/personas/{persona_id}")
async def delete_persona(persona_id: str):
    try:
        bundle = await asyncio.get_running_loop().run_in_executor(
            _executor, lambda: engine.delete_persona(persona_id)
        )
        return {"ok": True, **bundle}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to delete persona")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/memory/coding")
async def memory_coding_learn(request: Request):
    """
    Let Blossom Assistant (or other clients) store a coding lesson into Chroma.
    Body JSON: { "user_prompt": str, "answer": str, "source": str }
    """
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    user_prompt = str(body.get("user_prompt") or body.get("prompt") or "").strip()
    answer = str(body.get("answer") or body.get("text") or "").strip()
    source = str(body.get("source") or "extension").strip() or "extension"
    if not user_prompt:
        raise HTTPException(status_code=400, detail="user_prompt is required")
    if not answer:
        raise HTTPException(status_code=400, detail="answer is required")

    try:
        memory_id = await asyncio.get_running_loop().run_in_executor(
            _executor,
            lambda: learn_coding_lesson(user_prompt, answer, source=source),
        )
    except Exception as exc:
        logger.exception("memory/coding learn failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not memory_id:
        return {
            "ok": False,
            "stored": False,
            "reason": "answer not useful enough to store",
        }
    return {"ok": True, "stored": True, "id": memory_id, "source": source}


@app.get("/v1/memory/coding")
async def memory_coding_search(q: str = "", n: int = 5):
    """Search coding_lessons (for debugging / extension verification)."""
    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="q is required")
    limit = max(1, min(int(n or 5), 20))

    def _search():
        return query_memories(query, collection=COLLECTION_CODING, top_k=limit)

    try:
        hits = await asyncio.get_running_loop().run_in_executor(_executor, _search)
    except Exception as exc:
        logger.exception("memory/coding search failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "ok": True,
        "query": query,
        "count": len(hits),
        "memories": [
            {
                "id": h.get("id"),
                "text": (h.get("text") or "")[:1200],
                "metadata": h.get("metadata") or {},
                "distance": h.get("distance"),
            }
            for h in hits
        ],
    }


@app.post("/v1/chat/completions")
async def route_chat(request: Request):
    body = await request.json()
    incoming_messages = body.get("messages") or []
    if not incoming_messages:
        raise HTTPException(status_code=400, detail="messages is required")

    last_user_message = ""
    for message in reversed(incoming_messages):
        if message.get("role") == "user":
            last_user_message = _message_text(message)
            break
    if not last_user_message:
        raise HTTPException(status_code=400, detail="No user message found")

    want_stream = bool(body.get("stream"))
    locale = normalize_locale(
        body.get("blossom_locale")
        or body.get("locale")
        or body.get("language")
    )

    if not want_stream:
        try:
            def _run_sync():
                final, _pending = run_chat_pipeline(
                    last_user_message,
                    None,
                    defer_voice=False,
                    locale=locale,
                )
                return final

            return await asyncio.get_running_loop().run_in_executor(
                _executor, _run_sync
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Chat pipeline failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    queue: Queue = Queue()
    chunk_id = f"chatcmpl-{int(time.time() * 1000)}"

    def on_progress(event: dict) -> None:
        queue.put(("thought", event))

    def worker() -> None:
        try:
            final, pending_speak = run_chat_pipeline(
                last_user_message,
                on_progress=on_progress,
                defer_voice=VOICE_DEFER_STREAM,
                locale=locale,
            )
            # Stream text first; keep SSE open until TTS finishes (stop comes after audio).
            queue.put(("final", final))
            emotion = str(final.get("blossom_emotion") or "")
            if pending_speak:
                logger.info(
                    "voice: synthesizing emotion=%s chars=%s locale=%s",
                    emotion,
                    len(pending_speak),
                    locale,
                )
                updated = synthesize_and_attach(
                    final,
                    pending_speak,
                    locale=locale,
                    voice_id=_active_voice_id(),
                    complete_fn=_local_completion,
                    message_text_fn=_message_text,
                    on_progress=on_progress,
                )
                audio_url = updated.get("blossom_audio_url")
                if audio_url:
                    logger.info("voice: ready %s", audio_url)
                    queue.put(
                        (
                            "audio",
                            {
                                "audio_url": audio_url,
                                "emotion": updated.get("blossom_emotion"),
                            },
                        )
                    )
                else:
                    logger.warning("voice: synthesize failed emotion=%s", emotion)
                    queue.put(
                        (
                            "audio",
                            {
                                "audio_url": None,
                                "emotion": updated.get("blossom_emotion") or emotion,
                                "failed": True,
                            },
                        )
                    )
            else:
                logger.info(
                    "voice: skip emotion=%s enabled=%s",
                    emotion or "(none)",
                    VOICE_ENABLED,
                )
            queue.put(("stop", None))
        except HTTPException as exc:
            queue.put(("error", {"status_code": exc.status_code, "detail": exc.detail}))
        except Exception as exc:
            logger.exception("Streaming chat pipeline failed")
            queue.put(("error", {"status_code": 500, "detail": str(exc)}))
        finally:
            queue.put(("end", None))

    threading.Thread(target=worker, daemon=True, name="chatrouter-stream").start()

    async def event_stream():
        while True:
            kind, payload = await asyncio.to_thread(queue.get)
            if kind == "thought":
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            elif kind == "final":
                text = ""
                try:
                    text = _message_text(payload["choices"][0]["message"])
                except Exception:
                    text = ""
                intel_source = payload.get("blossom_intel_source")
                intel_label = payload.get("blossom_intel_label") or _label_intel_source(
                    intel_source if isinstance(intel_source, str) else None
                )
                if intel_source:
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "object": "blossom.intel",
                                "source": intel_source,
                                "label": intel_label,
                            },
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "object": "blossom.thoughts",
                            "thoughts": payload.get("blossom_thoughts") or [],
                            "source": intel_source,
                            "label": intel_label,
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )
                # Emotion chip can show before Play is ready — only for speakable emotions.
                emotion = payload.get("blossom_emotion")
                emotion_l = str(emotion or "").strip().lower()
                if (
                    emotion_l in SPEAK_EMOTIONS
                    and not payload.get("blossom_audio_url")
                ):
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "object": "blossom.audio",
                                "audio_url": None,
                                "emotion": emotion_l,
                                "pending": True,
                            },
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )
                elif emotion_l:
                    # Non-speakable label only (should be rare now).
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "object": "blossom.audio",
                                "audio_url": None,
                                "emotion": emotion_l,
                                "pending": False,
                            },
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )
                audio_url = payload.get("blossom_audio_url")
                if audio_url:
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "object": "blossom.audio",
                                "audio_url": audio_url,
                                "emotion": emotion,
                            },
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )
                if text:
                    step = 48
                    for i in range(0, len(text), step):
                        piece = text[i : i + step]
                        yield (
                            "data: "
                            + json.dumps(
                                _openai_content_chunk(piece, chunk_id),
                                ensure_ascii=False,
                            )
                            + "\n\n"
                        )
                        await asyncio.sleep(0)
                # Do not send stop here — worker emits "stop" after TTS so the
                # client keeps the SSE open for blossom.audio.
            elif kind == "stop":
                yield (
                    "data: "
                    + json.dumps(_openai_stop_chunk(chunk_id), ensure_ascii=False)
                    + "\n\n"
                )
            elif kind == "audio":
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "object": "blossom.audio",
                            "audio_url": payload.get("audio_url"),
                            "emotion": payload.get("emotion"),
                            "failed": bool(payload.get("failed")),
                            "pending": bool(
                                payload.get("pending")
                                or (
                                    not payload.get("audio_url")
                                    and not payload.get("failed")
                                )
                            ),
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )
            elif kind == "error":
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "object": "error",
                            "message": payload.get("detail"),
                            "code": payload.get("status_code", 500),
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )
                yield (
                    "data: "
                    + json.dumps(_openai_stop_chunk(chunk_id), ensure_ascii=False)
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"
                break
            elif kind == "end":
                yield "data: [DONE]\n\n"
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Blossom-Thoughts": "1",
        },
    )

if __name__ == "__main__":
    logger.info(
        "Cloud policy: enabled=%s order=%s escalate_incomplete=%s escalate_request=%s",
        CLOUD_FALLBACK_ENABLED,
        CLOUD_FALLBACK_ORDER,
        CLOUD_ESCALATE_ON_INCOMPLETE,
        CLOUD_ESCALATE_ON_REQUEST,
    )
    if not server_manager.coder_available():
        logger.warning(
            "Coder model not found yet (%s). Coding routes will use cloud until it exists.",
            CODER_MODEL,
        )
    if CLAUDE_CLIENT is None and GEMINI_CLIENT is None:
        logger.warning(
            "No cloud keys set (CLAUDE_API_KEY / GEMINI_API_KEY) — last-resort fallback disabled."
        )
    elif CLAUDE_CLIENT is None:
        logger.warning("CLAUDE_API_KEY not set — Claude fallback disabled.")
    elif GEMINI_CLIENT is None:
        logger.warning("GEMINI_API_KEY not set — Gemini fallback disabled.")
    uvicorn.run(app, host=ROUTER_HOST, port=ROUTER_PORT)
