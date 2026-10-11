"""ChatRouter-facing agent loop: LLM drafts code → sandbox executes → concise answer."""

from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib import error, request

ProgressFn = Callable[[dict[str, Any]], None]

_PYTHON_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S | re.I)


def agent_executor_url(base: str | None = None) -> str:
    import os

    return (base or os.getenv("AGENT_EXECUTOR_URL") or "http://127.0.0.1:8082").rstrip(
        "/"
    )


def agent_executor_healthy(base: str | None = None, timeout: float = 2.0) -> bool:
    url = f"{agent_executor_url(base)}/health"
    try:
        with request.urlopen(url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return bool(body.get("ok"))
    except (error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False


def load_agent_system_prompt(base: str | None = None, *, compact: bool = True) -> str:
    import os

    env_compact = os.getenv("AGENT_PROMPT_COMPACT", "true").strip().lower()
    if env_compact in {"0", "false", "no", "off"}:
        compact = False

    query = "?compact=1" if compact else "?compact=0"
    url = f"{agent_executor_url(base)}/v1/prompt{query}"
    try:
        with request.urlopen(url, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            prompt = str(body.get("prompt") or "").strip()
            if prompt:
                return prompt
    except (error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        pass

    from pathlib import Path

    root = Path(__file__).resolve().parent / "prompts"
    chosen = (
        root / "agent_system_prompt_compact.md"
        if compact
        else root / "agent_system_prompt.md"
    )
    fallback = root / "agent_system_prompt.md"
    if chosen.is_file():
        return chosen.read_text(encoding="utf-8")
    if fallback.is_file():
        return fallback.read_text(encoding="utf-8")
    return "You are a Code Execution Agent. Prefer agent_utils (import agent_utils as au). Set _result= for compact output."


def extract_python_blocks(text: str) -> list[str]:
    return [block.strip() for block in _PYTHON_FENCE.findall(text or "") if block.strip()]


def execute_python(code: str, base: str | None = None, timeout: float = 35.0) -> dict[str, Any]:
    payload = json.dumps({"code": code}).encode("utf-8")
    req = request.Request(
        f"{agent_executor_url(base)}/v1/execute",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _format_exec_result(index: int, result: dict[str, Any]) -> str:
    parts = [f"### Execution {index}"]
    if result.get("result"):
        parts.append("result:\n" + str(result["result"]).rstrip())
    if result.get("stdout"):
        parts.append("stdout:\n" + str(result["stdout"]).rstrip())
    if result.get("stderr"):
        parts.append("stderr:\n" + str(result["stderr"]).rstrip())
    if result.get("error"):
        parts.append("error:\n" + str(result["error"]).rstrip())
    parts.append(f"workspace: {result.get('workspace', '')}")
    return "\n".join(parts)


def run_agent_execution_turn(
    user_prompt: str,
    *,
    complete_fn: Callable[[list[dict[str, str]], float], str],
    on_progress: ProgressFn | None = None,
    base_url: str | None = None,
    temperature: float = 0.15,
    max_rounds: int = 2,
) -> str:
    """
    complete_fn(messages, temperature) -> assistant text (local coder or cloud).
    Runs up to max_rounds: draft code → execute → optional self-correction.
    """
    system_prompt = load_agent_system_prompt(base_url)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"{user_prompt.strip()}\n\n"
                "Reply with a brief plan, then one ```python``` block using agent_utils "
                "when possible. Save outputs under ./workspace/. "
                "Set _result= to the answer (path, number, or small dict) — avoid printing large frames."
            ),
        },
    ]

    transcript = ""
    exec_notes: list[str] = []

    for round_idx in range(max(1, max_rounds)):
        if on_progress:
            on_progress(
                {
                    "object": "blossom.thought",
                    "step": "agent_draft",
                    "message": f"Agent execution round {round_idx + 1}…",
                    "round": round_idx + 1,
                }
            )
        draft = complete_fn(messages, temperature).strip()
        transcript = draft
        blocks = extract_python_blocks(draft)
        if not blocks:
            return draft

        round_results: list[str] = []
        for i, code in enumerate(blocks, start=1):
            if on_progress:
                on_progress(
                    {
                        "object": "blossom.thought",
                        "step": "agent_execute",
                        "message": f"Running sandbox Python block {i}/{len(blocks)}…",
                    }
                )
            try:
                result = execute_python(code, base=base_url)
            except Exception as exc:
                result = {"ok": False, "stdout": "", "stderr": "", "error": str(exc)}
            round_results.append(_format_exec_result(i, result))

        exec_notes.extend(round_results)
        combined = "\n\n".join(round_results)
        all_ok = all("error:\n" not in chunk for chunk in round_results)

        if all_ok or round_idx + 1 >= max_rounds:
            if on_progress:
                on_progress(
                    {
                        "object": "blossom.thought",
                        "step": "agent_summarize",
                        "message": "Summarizing execution results…",
                    }
                )
            messages.extend(
                [
                    {"role": "assistant", "content": draft},
                    {
                        "role": "user",
                        "content": (
                            "Sandbox results:\n\n"
                            f"{combined}\n\n"
                            "Give a concise final answer with exact computed values and "
                            "any ./workspace/ output paths. No new code fences unless something failed."
                        ),
                    },
                ]
            )
            summary = complete_fn(messages, max(0.1, temperature - 0.05)).strip()
            return summary or draft

        messages.extend(
            [
                {"role": "assistant", "content": draft},
                {
                    "role": "user",
                    "content": (
                        "Execution failed. Fix and return ONE corrected ```python``` block.\n\n"
                        f"{combined}"
                    ),
                },
            ]
        )

    footer = "\n\n---\n**Sandbox log**\n" + "\n\n".join(exec_notes)
    return (transcript + footer).strip()
