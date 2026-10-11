"""Run eval harness steps on Blossom boot (after ChatRouter is listening)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# startup.py lives at tools/eval/blossom_eval/ → parent[1] is tools/eval/
EVAL_DIR = Path(__file__).resolve().parents[1]
RUN_EVAL = EVAL_DIR / "run_eval.py"


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _health_url() -> str:
    host = os.getenv("CHAT_ROUTER_HOST", "127.0.0.1")
    port = os.getenv("CHAT_ROUTER_PORT", "8081")
    return f"http://{host}:{port}/health"


def _wait_for_health(timeout_sec: float = 120.0, interval_sec: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_sec
    url = _health_url()
    while time.monotonic() < deadline:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(interval_sec)
    return False


def _run_step(args: list[str]) -> int:
    cmd = [sys.executable, str(RUN_EVAL), *args]
    logger.info("[Blossom Eval] %s", " ".join(args))
    result = subprocess.run(
        cmd,
        cwd=str(EVAL_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            logger.info("[Blossom Eval] %s", line)
    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            logger.warning("[Blossom Eval] %s", line)
    if result.returncode != 0:
        logger.warning("[Blossom Eval] exit %s for: %s", result.returncode, args)
    return result.returncode


def run_startup_eval_suite() -> None:
    """
    list → dry-run → live run → report for EVAL_CORPUS (default php-modernization).
    Skipped when EVAL_ON_STARTUP=false.
    """
    if not _env_flag("EVAL_ON_STARTUP", default=True):
        logger.info("[Blossom Eval] skipped (EVAL_ON_STARTUP=false)")
        return

    if not RUN_EVAL.is_file():
        logger.warning("[Blossom Eval] missing %s", RUN_EVAL)
        return

    corpus = os.getenv("EVAL_CORPUS", "php-modernization").strip() or "php-modernization"
    dry_only = _env_flag("EVAL_ON_STARTUP_DRY_RUN_ONLY", default=False)

    _run_step(["list"])

    dry_code = _run_step(["run", "--corpus", corpus, "--dry-run"])
    if dry_code != 0:
        logger.warning("[Blossom Eval] dry-run failed — skipping live eval")

    if dry_only:
        logger.info("[Blossom Eval] live run skipped (EVAL_ON_STARTUP_DRY_RUN_ONLY=true)")
        _run_step(["report", "--corpus", corpus])
        return

    if dry_code != 0:
        _run_step(["report", "--corpus", corpus])
        return

    if not _wait_for_health():
        logger.warning("[Blossom Eval] ChatRouter /health not ready — skipping live eval")
        _run_step(["report", "--corpus", corpus])
        return

    _run_step(["run", "--corpus", corpus])
    _run_step(["report", "--corpus", corpus])
