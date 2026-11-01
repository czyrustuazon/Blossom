"""
Manage a single llama-server process and hot-swap GGUF models on one GPU.

Roles:
  persona — conversational GGUF
  coder   — any coding GGUF (primary or alt); pass model_path to pick which file
"""

from __future__ import annotations

import logging
import os
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
load_dotenv(SCRIPT_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

from LocalModels import (  # noqa: E402
    any_coder_available,
    persona_model,
    primary_coder,
)
from MemoryUpdater import (  # noqa: E402
    LLAMA_SERVER_EXE,
    LLAMA_SERVER_URL,
    RUNTIME_DIR,
)

logger = logging.getLogger(__name__)

# Back-compat exports used by ChatRouter / health
PERSONA_MODEL = persona_model().path
CODER_MODEL = primary_coder().path

LLAMA_PORT = int(os.getenv("LLAMA_SERVER_PORT", "11434"))
# Qwen3-14B is trained at 32768. The default matches that window (fp16 KV is ~5 GB).
PERSONA_CTX = int(os.getenv("PERSONA_CTX_SIZE", "32768"))
# Estimate for 32k fp16 KV + Q4 weights + compute buffers, so --fit still runs when
# voice TTS has already taken a chunk of the 24 GB card.
PERSONA_VRAM_MIB = int(os.getenv("PERSONA_VRAM_MIB", "18000"))


@dataclass(frozen=True)
class CoderProfile:
    """One way to launch the coder: context size, KV cache type, MoE layers kept on CPU."""

    ctx: int
    cache_type: str = "f16"
    n_cpu_moe: int = 0
    # Measured VRAM for this launch; 0 = unknown (always let --fit decide).
    vram_mib: int = 0


def _parse_coder_profiles(raw: str) -> list[CoderProfile]:
    """CODER_CTX_PROFILES="65536:q8_0:0:21400,…" (ctx[:cache[:n_cpu_moe[:vram_mib]]])."""
    profiles: list[CoderProfile] = []
    for part in (raw or "").split(","):
        bits = [b.strip() for b in part.split(":") if b.strip()]
        if not bits:
            continue
        try:
            profiles.append(
                CoderProfile(
                    ctx=int(bits[0]),
                    cache_type=bits[1] if len(bits) > 1 else "f16",
                    n_cpu_moe=int(bits[2]) if len(bits) > 2 else 0,
                    vram_mib=int(bits[3]) if len(bits) > 3 else 0,
                )
            )
        except ValueError:
            logger.warning("Ignoring bad CODER_CTX_PROFILES entry: %r", part)
    return sorted(profiles, key=lambda p: p.ctx)


# Smallest profile that fits a request is used; larger ones trade speed for room
# (quantized KV + experts on CPU). Without profiles: one CODER_CTX_SIZE launch.
CODER_PROFILES = _parse_coder_profiles(os.getenv("CODER_CTX_PROFILES", "")) or [
    CoderProfile(
        ctx=int(os.getenv("CODER_CTX_SIZE", "32768")),
        cache_type=os.getenv("CODER_CACHE_TYPE", "f16").strip() or "f16",
        n_cpu_moe=int(os.getenv("CODER_N_CPU_MOE", "0")),
    )
]
# Largest coder window — budgets (session pack, health) size against this.
CODER_CTX = CODER_PROFILES[-1].ctx


def coder_profile_for(min_ctx: int) -> CoderProfile:
    for profile in CODER_PROFILES:
        if profile.ctx >= min_ctx:
            return profile
    return CODER_PROFILES[-1]
# Shared default; role-specific overrides let big coders spill layers to CPU/RAM.
_DEFAULT_GPU_LAYERS = int(os.getenv("LLAMA_N_GPU_LAYERS", "999"))
PERSONA_GPU_LAYERS = int(os.getenv("PERSONA_N_GPU_LAYERS", str(_DEFAULT_GPU_LAYERS)))
CODER_GPU_LAYERS = int(os.getenv("CODER_N_GPU_LAYERS", str(_DEFAULT_GPU_LAYERS)))
# Back-compat alias used by health / older callers
GPU_LAYERS = _DEFAULT_GPU_LAYERS
LLAMA_THREADS = int(os.getenv("LLAMA_THREADS", "0"))  # 0 = llama.cpp default
# Free-VRAM margin for llama-server --fit. Windows (WDDM) starts spilling to shared
# memory well before the card is full: 1024 still spilled at 64k, 3072 did not.
# 0 = pin --n-gpu-layers instead.
LLAMA_FIT_TARGET_MIB = int(os.getenv("LLAMA_FIT_TARGET_MIB", "3072"))
# Headroom over a profile's measured VRAM (which already includes compute buffers)
# before pinning all layers on GPU without the fit probe.
PINNED_MARGIN_MIB = int(os.getenv("LLAMA_PINNED_MARGIN_MIB", "1024"))
# --no-mmap reads the whole GGUF into RAM. Only do that when free RAM covers the
# file plus this margin, so a 32 GB machine does not page the 18 GB coder.
MMAP_DISABLE_MARGIN_MIB = int(os.getenv("LLAMA_MMAP_DISABLE_MARGIN_MIB", "4096"))
READY_TIMEOUT_SEC = int(os.getenv("LLAMA_READY_TIMEOUT_SEC", "600"))
# Persona chat: off = much faster (no long CoT). Coder can keep thinking.
PERSONA_REASONING = os.getenv("PERSONA_REASONING", "off").strip().lower()
CODER_REASONING = os.getenv("CODER_REASONING", "auto").strip().lower()
FLASH_ATTN = os.getenv("LLAMA_FLASH_ATTN", "on").strip().lower()
HEALTH_URL = f"{LLAMA_SERVER_URL.rstrip('/')}/health"
PID_FILE = PROJECT_ROOT / "Mind" / "llama-server.pid"
ROLE_FILE = PROJECT_ROOT / "Mind" / "llama-server.role"
MODEL_FILE = PROJECT_ROOT / "Mind" / "llama-server.model"


def _normalize_reasoning(value: str) -> str:
    if value in {"on", "off", "auto"}:
        return value
    if value in {"0", "false", "no", "disable", "disabled"}:
        return "off"
    if value in {"1", "true", "yes", "enable", "enabled"}:
        return "on"
    return "auto"


def _free_vram_mib() -> int | None:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            text=True,
            timeout=5,
        )
        return int(out.strip().splitlines()[0])
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return None


def _gpu_layers_for(role: str) -> int:
    return PERSONA_GPU_LAYERS if role == "persona" else CODER_GPU_LAYERS


def _read_gguf_string(handle) -> str:
    (length,) = struct.unpack("<Q", handle.read(8))
    return handle.read(length).decode("utf-8", "replace")


def _skip_gguf_value(handle, vtype: int) -> None:
    sizes = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
    if vtype in sizes:
        handle.read(sizes[vtype])
        return
    if vtype == 8:
        _read_gguf_string(handle)
        return
    if vtype == 9:
        (elem_type,) = struct.unpack("<I", handle.read(4))
        (count,) = struct.unpack("<Q", handle.read(8))
        for _ in range(count):
            _skip_gguf_value(handle, elem_type)
        return
    raise ValueError(f"unknown gguf type {vtype}")


def gguf_context_length(path: Path) -> int | None:
    """Trained context length from a GGUF header, or None if it cannot be read."""
    try:
        with path.open("rb") as handle:
            if handle.read(4) != b"GGUF":
                return None
            (version,) = struct.unpack("<I", handle.read(4))
            if version < 2:
                return None
            handle.read(8)  # tensor count
            (n_kv,) = struct.unpack("<Q", handle.read(8))
            arch: str | None = None
            ctx_types = {4: "<I", 5: "<i", 10: "<Q", 11: "<q"}
            for _ in range(n_kv):
                key = _read_gguf_string(handle)
                (vtype,) = struct.unpack("<I", handle.read(4))
                if key == "general.architecture" and vtype == 8:
                    arch = _read_gguf_string(handle)
                    continue
                if arch and key == f"{arch}.context_length" and vtype in ctx_types:
                    width = 4 if vtype in {4, 5} else 8
                    return int(struct.unpack(ctx_types[vtype], handle.read(width))[0])
                _skip_gguf_value(handle, vtype)
    except (OSError, ValueError, struct.error):
        return None
    return None


def cap_ctx_to_trained(ctx: int, model_path: Path) -> int:
    """Keep the launch window inside the context the GGUF was trained for."""
    trained = gguf_context_length(model_path)
    if trained and ctx > trained:
        logger.info(
            "Capping ctx %s to trained context %s for %s",
            ctx,
            trained,
            model_path.name,
        )
        return trained
    return ctx


def _free_ram_mib() -> int | None:
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.ullAvailPhys // (1024 * 1024))
    except (AttributeError, OSError, ValueError):
        return None


def should_disable_mmap(model_path: Path, n_cpu_moe: int, free_ram_mib: int | None) -> bool:
    """Copy the GGUF into RAM when CPU experts would otherwise fault through mmap."""
    if n_cpu_moe <= 0 or free_ram_mib is None:
        return False
    try:
        file_mib = model_path.stat().st_size // (1024 * 1024)
    except OSError:
        return False
    return free_ram_mib >= file_mib + MMAP_DISABLE_MARGIN_MIB


class LlamaServerManager:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.current_role: str | None = None
        self.current_model: Path | None = None
        self.current_ctx: int | None = None

    def coder_available(self) -> bool:
        return any_coder_available()

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
        self.current_model = None
        self.current_ctx = None
        for path in (PID_FILE, ROLE_FILE, MODEL_FILE):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def start(
        self,
        role: str,
        model_path: Path | None = None,
        profile: CoderProfile | None = None,
    ) -> None:
        if role not in {"persona", "coder"}:
            raise ValueError(f"Unknown role: {role}")

        cache_type = "f16"
        n_cpu_moe = 0
        vram_mib = 0
        if role == "persona":
            model_path = (model_path or persona_model().path).resolve()
            ctx = PERSONA_CTX
            vram_mib = PERSONA_VRAM_MIB
            reasoning_raw = PERSONA_REASONING
        else:
            model_path = (model_path or primary_coder().path).resolve()
            if not model_path.is_file():
                raise FileNotFoundError(f"Coder model not found: {model_path}")
            profile = profile or CODER_PROFILES[0]
            ctx = profile.ctx
            cache_type = profile.cache_type
            n_cpu_moe = profile.n_cpu_moe
            vram_mib = profile.vram_mib
            reasoning_raw = CODER_REASONING

        if not model_path.is_file():
            raise FileNotFoundError(f"Model not found: {model_path}")
        if not LLAMA_SERVER_EXE.is_file():
            raise FileNotFoundError(f"llama-server.exe not found: {LLAMA_SERVER_EXE}")

        ctx = cap_ctx_to_trained(ctx, model_path)
        # One slot owns the whole window. llama-server's auto default is 4 slots
        # sharing one KV pool, so a long prompt can be rejected while idle slots
        # still hold cache. Blossom serves one request at a time.
        disable_mmap = should_disable_mmap(
            model_path, n_cpu_moe, _free_ram_mib() if n_cpu_moe > 0 else None
        )

        self.stop()
        mind_dir = PROJECT_ROOT / "Mind"
        mind_dir.mkdir(parents=True, exist_ok=True)

        gpu_layers = _gpu_layers_for(role)
        args = [
            str(LLAMA_SERVER_EXE),
            "-m",
            str(model_path),
            "--ctx-size",
            str(ctx),
            "--port",
            str(LLAMA_PORT),
            "--host",
            "127.0.0.1",
            "--jinja",
            "--parallel",
            "1",
        ]
        # Fit layers / experts to the VRAM that is actually free (TTS, vision, browser
        # come and go); pinning --n-gpu-layers would disable the fit. The fit probe adds
        # ~15 s to a load, so skip it when the measured footprint clearly fits.
        free = _free_vram_mib() if LLAMA_FIT_TARGET_MIB > 0 else None
        use_fit = LLAMA_FIT_TARGET_MIB > 0 and not (
            vram_mib and free is not None and free - PINNED_MARGIN_MIB >= vram_mib
        )
        if use_fit:
            args.extend(["--fit", "on", "--fit-target", str(LLAMA_FIT_TARGET_MIB)])
        else:
            args.extend(["--n-gpu-layers", str(gpu_layers)])
        if LLAMA_THREADS > 0:
            args.extend(["--threads", str(LLAMA_THREADS)])

        fa = FLASH_ATTN if FLASH_ATTN in {"on", "off", "auto"} else "auto"
        args.extend(["--flash-attn", fa])
        if cache_type != "f16":
            # Quantized V cache needs flash attention.
            args.extend(["--cache-type-k", cache_type, "--cache-type-v", cache_type])
        if n_cpu_moe > 0:
            args.extend(["--n-cpu-moe", str(n_cpu_moe)])
        if disable_mmap:
            args.append("--no-mmap")

        reasoning = _normalize_reasoning(reasoning_raw)
        args.extend(["--reasoning", reasoning])
        if reasoning == "off":
            args.extend(["--reasoning-budget", "0"])

        log_path = mind_dir / f"llama-server-{role}.log"
        log_file = open(log_path, "w", encoding="utf-8", errors="replace")
        logger.info(
            "Starting llama-server role=%s model=%s gpu_layers=%s ctx=%s "
            "cache=%s n_cpu_moe=%s mmap=%s parallel=1 reasoning=%s flash_attn=%s",
            role,
            model_path.name,
            f"fit(margin {LLAMA_FIT_TARGET_MIB} MiB, free {free} MiB)" if use_fit else gpu_layers,
            ctx,
            cache_type,
            n_cpu_moe,
            "off" if disable_mmap else "on",
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
        MODEL_FILE.write_text(str(model_path), encoding="utf-8")
        self.current_role = role
        self.current_model = model_path
        self.current_ctx = ctx
        self.wait_until_healthy(timeout_sec=READY_TIMEOUT_SEC)
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

    def ensure(
        self,
        role: str,
        model_path: Path | None = None,
        *,
        min_ctx: int = 0,
    ) -> None:
        """
        Make `role` the live model. For the coder, min_ctx picks the smallest profile
        that fits; a running coder is reused while its window is big enough (keeps the
        prompt cache), and relaunched with a larger profile only when it is not.
        """
        if role == "persona":
            target = (model_path or persona_model().path).resolve()
        else:
            target = (model_path or primary_coder().path).resolve()

        if (
            self.current_role == role
            and self.current_model == target
            and (role != "coder" or (self.current_ctx or 0) >= min_ctx)
            and self.is_healthy()
        ):
            return

        if role == "coder":
            profile = coder_profile_for(min_ctx)
            if self.current_role == "coder" and self.current_model == target:
                logger.info(
                    "Coder window %s < needed %s — relaunching at ctx=%s (%s KV, %s MoE layers on CPU)",
                    self.current_ctx,
                    min_ctx,
                    profile.ctx,
                    profile.cache_type,
                    profile.n_cpu_moe,
                )
            self.start(role, model_path=target, profile=profile)
            return

        if self.is_healthy() and ROLE_FILE.exists() and MODEL_FILE.exists():
            disk_role = ROLE_FILE.read_text(encoding="utf-8").strip()
            disk_model = Path(MODEL_FILE.read_text(encoding="utf-8").strip())
            if (
                disk_role == role
                and disk_model.resolve() == target
                and self.process is None
            ):
                # External process already serving the desired model
                self.current_role = role
                self.current_model = target
                return

        self.start(role, model_path=target)


# Singleton used by ChatRouter
server_manager = LlamaServerManager()
