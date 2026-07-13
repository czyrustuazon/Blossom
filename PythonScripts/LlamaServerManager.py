"""
Manage a single llama-server process and hot-swap GGUF models on one GPU.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
load_dotenv(SCRIPT_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

from MemoryUpdater import (  # noqa: E402
    CONVERSATIONAL_MODEL,
    LLAMA_SERVER_EXE,
    LLAMA_SERVER_URL,
    RUNTIME_DIR,
)

logger = logging.getLogger(__name__)

PERSONA_MODEL = Path(
    os.getenv("PERSONA_MODEL_PATH", str(CONVERSATIONAL_MODEL))
)
CODER_MODEL = Path(
    os.getenv(
        "CODER_MODEL_PATH",
        str(
            PROJECT_ROOT
            / "Brains"
            / "models"
            / "coding"
            / "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"
        ),
    )
)
LLAMA_PORT = int(os.getenv("LLAMA_SERVER_PORT", "11434"))
PERSONA_CTX = int(os.getenv("PERSONA_CTX_SIZE", "16384"))
CODER_CTX = int(os.getenv("CODER_CTX_SIZE", "16384"))
GPU_LAYERS = int(os.getenv("LLAMA_N_GPU_LAYERS", "999"))
# Persona chat: off = much faster (no long CoT). Coder can keep thinking.
PERSONA_REASONING = os.getenv("PERSONA_REASONING", "off").strip().lower()
CODER_REASONING = os.getenv("CODER_REASONING", "auto").strip().lower()
FLASH_ATTN = os.getenv("LLAMA_FLASH_ATTN", "on").strip().lower()
HEALTH_URL = f"{LLAMA_SERVER_URL.rstrip('/')}/health"
PID_FILE = PROJECT_ROOT / "Mind" / "llama-server.pid"
ROLE_FILE = PROJECT_ROOT / "Mind" / "llama-server.role"


def _normalize_reasoning(value: str) -> str:
    if value in {"on", "off", "auto"}:
        return value
    if value in {"0", "false", "no", "disable", "disabled"}:
        return "off"
    if value in {"1", "true", "yes", "enable", "enabled"}:
        return "on"
    return "auto"


class LlamaServerManager:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.current_role: str | None = None

    def coder_available(self) -> bool:
        return CODER_MODEL.is_file()

    def is_healthy(self, timeout: float = 2.0) -> bool:
        try:
            response = requests.get(HEALTH_URL, timeout=timeout)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            logger.info("Stopping llama-server PID %s", self.process.pid)
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
        self.current_role = None
        for path in (PID_FILE, ROLE_FILE):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def start(self, role: str) -> None:
        if role not in {"persona", "coder"}:
            raise ValueError(f"Unknown role: {role}")
        if role == "coder" and not self.coder_available():
            raise FileNotFoundError(f"Coder model not found: {CODER_MODEL}")

        model_path = PERSONA_MODEL if role == "persona" else CODER_MODEL
        ctx = PERSONA_CTX if role == "persona" else CODER_CTX
        if not model_path.is_file():
            raise FileNotFoundError(f"Model not found: {model_path}")
        if not LLAMA_SERVER_EXE.is_file():
            raise FileNotFoundError(f"llama-server.exe not found: {LLAMA_SERVER_EXE}")

        self.stop()
        mind_dir = PROJECT_ROOT / "Mind"
        mind_dir.mkdir(parents=True, exist_ok=True)

        args = [
            str(LLAMA_SERVER_EXE),
            "-m",
            str(model_path),
            "--ctx-size",
            str(ctx),
            "--n-gpu-layers",
            str(GPU_LAYERS),
            "--port",
            str(LLAMA_PORT),
            "--host",
            "127.0.0.1",
            "--jinja",
        ]
        fa = FLASH_ATTN if FLASH_ATTN in {"on", "off", "auto"} else "auto"
        args.extend(["--flash-attn", fa])

        reasoning = _normalize_reasoning(
            PERSONA_REASONING if role == "persona" else CODER_REASONING
        )
        args.extend(["--reasoning", reasoning])
        if reasoning == "off":
            args.extend(["--reasoning-budget", "0"])

        log_path = mind_dir / f"llama-server-{role}.log"
        log_file = open(log_path, "w", encoding="utf-8", errors="replace")
        logger.info(
            "Starting llama-server role=%s model=%s reasoning=%s flash_attn=%s",
            role,
            model_path.name,
            reasoning,
            fa,
        )
        self.process = subprocess.Popen(
            args,
            cwd=str(RUNTIME_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        PID_FILE.write_text(str(self.process.pid), encoding="utf-8")
        ROLE_FILE.write_text(role, encoding="utf-8")
        self.current_role = role
        self.wait_until_healthy(timeout_sec=300)
        logger.info("llama-server ready role=%s pid=%s", role, self.process.pid)

    def wait_until_healthy(self, timeout_sec: int = 300) -> None:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if self.process and self.process.poll() is not None:
                raise RuntimeError(
                    f"llama-server exited early with code {self.process.returncode}"
                )
            if self.is_healthy():
                return
            time.sleep(1)
        raise TimeoutError("Timed out waiting for llama-server /health")

    def ensure(self, role: str) -> None:
        if self.current_role == role and self.is_healthy():
            return
        if self.is_healthy() and ROLE_FILE.exists():
            disk_role = ROLE_FILE.read_text(encoding="utf-8").strip()
            if disk_role == role and self.process is None:
                # External process already serving the desired role
                self.current_role = role
                return
        self.start(role)


# Singleton used by ChatRouter
server_manager = LlamaServerManager()
