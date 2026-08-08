from __future__ import annotations

import os
from typing import Any

import requests


def chat_router_url() -> str:
    base = os.getenv("BLOSSOM_EVAL_CHAT_URL") or os.getenv("CHAT_ROUTER_URL")
    if base:
        return base.rstrip("/") + ("" if base.endswith("/v1/chat/completions") else "/v1/chat/completions")
    host = os.getenv("CHAT_ROUTER_HOST", "127.0.0.1")
    port = os.getenv("CHAT_ROUTER_PORT", "8081")
    return f"http://{host}:{port}/v1/chat/completions"


def health_ok(base_url: str | None = None) -> tuple[bool, str]:
    url = (base_url or chat_router_url()).replace("/v1/chat/completions", "/health")
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return True, f"ok ({data.get('status', 'healthy')})"
    except Exception as exc:
        return False, str(exc)


def ask_coder(prompt: str, *, timeout_sec: float = 600.0) -> str:
    payload: dict[str, Any] = {
        "model": os.getenv("BLOSSOM_EVAL_MODEL", "local-coder"),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.2,
    }
    resp = requests.post(chat_router_url(), json=payload, timeout=timeout_sec)
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("ChatRouter returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        content = "\n".join(parts)
    text = str(content).strip()
    if not text:
        reasoning = message.get("reasoning_content") or ""
        text = str(reasoning).strip()
    if not text:
        raise RuntimeError("Empty model response")
    return text
