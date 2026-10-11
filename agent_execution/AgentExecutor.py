"""
Sandboxed Python REPL API for the Blossom Code Execution Agent.

POST /v1/execute  — run Python code with agent_utils pre-imported
GET  /health      — liveness
GET  /v1/prompt   — system prompt text for the agent layer
"""

from __future__ import annotations

import io
import json
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)

WORKSPACE = Path(os.getenv("AGENT_WORKSPACE", str(ROOT / "workspace"))).resolve()
REPO_ROOT = Path(os.getenv("AGENT_REPO_ROOT", str(ROOT.parent))).resolve()
EXEC_TIMEOUT = max(5, int(os.getenv("AGENT_EXEC_TIMEOUT", "30")))
PROMPT_PATH = ROOT / "prompts" / "agent_system_prompt.md"
PROMPT_COMPACT_PATH = ROOT / "prompts" / "agent_system_prompt_compact.md"
STDOUT_MAX_CHARS = max(500, int(os.getenv("AGENT_EXEC_STDOUT_MAX", "1500")))
RESULT_MAX_CHARS = max(200, int(os.getenv("AGENT_EXEC_RESULT_MAX", "4000")))

WORKSPACE.mkdir(parents=True, exist_ok=True)


def _system_prompt(*, compact: bool = True) -> str:
    if compact and PROMPT_COMPACT_PATH.is_file():
        return PROMPT_COMPACT_PATH.read_text(encoding="utf-8")
    if PROMPT_PATH.is_file():
        return PROMPT_PATH.read_text(encoding="utf-8")
    return "Code Execution Agent — agent_utils pre-installed."


def _format_result(value: Any) -> str:
    try:
        if isinstance(value, (dict, list, tuple)):
            text = json.dumps(value, ensure_ascii=False, default=repr)
        else:
            text = repr(value)
    except (TypeError, ValueError):
        text = repr(value)
    if len(text) > RESULT_MAX_CHARS:
        return f"{text[:RESULT_MAX_CHARS]}…"
    return text


def _clip_stdout(text: str, *, has_result: bool) -> str:
    raw = (text or "").rstrip()
    if not raw:
        return ""
    limit = STDOUT_MAX_CHARS if has_result else min(STDOUT_MAX_CHARS * 2, 3000)
    if len(raw) <= limit:
        return raw
    return f"{raw[:limit]}\n…(stdout truncated {len(raw) - limit} chars — prefer _result=)"


def _safe_globals() -> dict[str, Any]:
    import agent_utils as au
    import numpy as np
    import pandas as pd

    return {
        "__builtins__": __builtins__,
        "__name__": "__main__",
        "agent_utils": au,
        "au": au,
        "pd": pd,
        "np": np,
        "WORKSPACE": WORKSPACE,
        "REPO_ROOT": REPO_ROOT,
    }


class ExecuteRequest(BaseModel):
    code: str = Field(..., min_length=1)
    timeout_seconds: int | None = Field(default=None, ge=1, le=120)


class ExecuteResponse(BaseModel):
    ok: bool
    stdout: str
    stderr: str
    result: str | None = None
    workspace: str
    error: str | None = None


app = FastAPI(title="Blossom Agent Sandbox", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "blossom-agent-sandbox",
        "workspace": str(WORKSPACE),
        "repo_root": str(REPO_ROOT),
        "timeout_seconds": EXEC_TIMEOUT,
    }


@app.get("/v1/prompt")
def get_prompt(compact: bool = Query(default=True)) -> dict[str, str]:
    return {"prompt": _system_prompt(compact=compact)}


@app.post("/v1/execute", response_model=ExecuteResponse)
def execute(req: ExecuteRequest) -> ExecuteResponse:
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="code must not be empty")

    # Change cwd so relative ./workspace/ paths resolve correctly.
    prev_cwd = Path.cwd()
    os.chdir(WORKSPACE)
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    result_value: str | None = None
    error: str | None = None

    try:
        globals_ns = _safe_globals()
        locals_ns: dict[str, Any] = {}
        compiled = compile(code, "<agent_repl>", "exec")
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(compiled, globals_ns, locals_ns)
            if "_result" in locals_ns:
                result_value = _format_result(locals_ns["_result"])
            elif "result" in locals_ns and locals_ns["result"] is not None:
                result_value = _format_result(locals_ns["result"])
    except Exception:
        error = traceback.format_exc()
    finally:
        os.chdir(prev_cwd)

    ok = error is None
    stdout_raw = stdout_buf.getvalue()
    stdout_out = _clip_stdout(stdout_raw, has_result=result_value is not None)
    stderr_out = stderr_buf.getvalue()
    if len(stderr_out) > STDOUT_MAX_CHARS:
        stderr_out = f"{stderr_out[:STDOUT_MAX_CHARS]}\n…(stderr truncated)"
    return ExecuteResponse(
        ok=ok,
        stdout=stdout_out,
        stderr=stderr_out,
        result=result_value,
        workspace=str(WORKSPACE),
        error=error,
    )


if __name__ == "__main__":
    host = os.getenv("AGENT_EXEC_HOST", "127.0.0.1")
    port = int(os.getenv("AGENT_EXEC_PORT", "8082"))
    uvicorn.run("AgentExecutor:app", host=host, port=port, reload=False)
