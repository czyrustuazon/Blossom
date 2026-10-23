"""
Per-client Mind stores.

Blossom Companion and Blossom Assistant share models and hardware, but never chat
history, persona state, or semantic memory. Each client ("surface") owns:

  Mind/companion/CompanionMind.db + Mind/companion/chromadb
  Mind/assistant/AssistantMind.db + Mind/assistant/chromadb

The active surface is request-scoped (a ContextVar) and must be set explicitly:
there is no default surface, so an untagged code path fails instead of silently
writing into Companion.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import time
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
load_dotenv(SCRIPT_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

# Overridable so tests never touch the real Mind folder.
MIND_ROOT = Path(os.getenv("BLOSSOM_MIND_ROOT") or (PROJECT_ROOT / "Mind"))

SURFACE_COMPANION = "companion"
SURFACE_ASSISTANT = "assistant"
SURFACES = (SURFACE_COMPANION, SURFACE_ASSISTANT)
VALID_SURFACES = frozenset(SURFACES)

_DB_NAMES = {
    SURFACE_COMPANION: "CompanionMind.db",
    SURFACE_ASSISTANT: "AssistantMind.db",
}

_ALIASES = {
    "companion": SURFACE_COMPANION,
    "blossom-companion": SURFACE_COMPANION,
    "blossomcompanion": SURFACE_COMPANION,
    "assistant": SURFACE_ASSISTANT,
    "blossom-assistant": SURFACE_ASSISTANT,
    "blossomassistant": SURFACE_ASSISTANT,
    "vscode": SURFACE_ASSISTANT,
    "ide": SURFACE_ASSISTANT,
    "extension": SURFACE_ASSISTANT,
}

CLIENT_HEADER = "x-blossom-client"


class SurfaceError(RuntimeError):
    status_code = 400


class SurfaceRequiredError(SurfaceError):
    status_code = 400


class SurfaceMismatchError(SurfaceError):
    status_code = 409


_SURFACE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "blossom_surface", default=None
)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def require_client_tag() -> bool:
    """Reject untagged client requests (BLOSSOM_REQUIRE_CLIENT, default on)."""
    return _env_flag("BLOSSOM_REQUIRE_CLIENT", True)


def normalize_surface(raw: object | None, *, has_session_pack: bool = False) -> str | None:
    """Map a client tag to companion|assistant; None when absent or unknown.

    Old Assistant builds sent blossom_session without a tag — a session pack is
    Assistant-only, so it identifies the client even when the tag is missing.
    """
    text = str(raw or "").strip().lower().replace("_", "-")
    if text in _ALIASES:
        return _ALIASES[text]
    if has_session_pack:
        return SURFACE_ASSISTANT
    return None


def _validated(surface: str) -> str:
    if surface not in VALID_SURFACES:
        raise SurfaceError(f"Unknown Blossom surface: {surface!r}")
    return surface


def pinned_surface() -> str | None:
    """Surface this process is dedicated to (split-router mode), if any."""
    raw = os.getenv("BLOSSOM_SURFACE")
    if not raw or not raw.strip():
        return None
    surface = normalize_surface(raw)
    if surface is None:
        raise SurfaceError(f"BLOSSOM_SURFACE={raw!r} is not companion|assistant")
    return surface


def current_surface() -> str | None:
    return _SURFACE.get() or pinned_surface()


def require_surface() -> str:
    surface = current_surface()
    if surface is None:
        raise SurfaceRequiredError(
            "No Blossom surface is active. Tag the request with blossom_client "
            "(companion|assistant) or run inside surface_scope()."
        )
    return surface


def set_surface(surface: str) -> contextvars.Token:
    return _SURFACE.set(_validated(surface))


def reset_surface(token: contextvars.Token) -> None:
    _SURFACE.reset(token)


@contextlib.contextmanager
def surface_scope(surface: str) -> Iterator[str]:
    token = set_surface(surface)
    try:
        yield surface
    finally:
        reset_surface(token)


def resolve_request_surface(
    *,
    header: str | None = None,
    query: str | None = None,
    body: dict[str, Any] | None = None,
    require: bool | None = None,
) -> str:
    """Pick the surface for one HTTP request.

    Precedence: X-Blossom-Client header, ?blossom_client=, body blossom_client /
    blossom_surface, then the blossom_session heuristic. A split router rejects
    requests tagged for the other client and attributes untagged ones to its own
    client. A shared router rejects untagged requests in strict mode; in lenient
    mode they go to the Assistant store — never into Companion.
    """
    payload = body if isinstance(body, dict) else {}
    raw = (
        header
        or query
        or payload.get("blossom_client")
        or payload.get("blossom_surface")
    )
    session = payload.get("blossom_session")
    has_session = isinstance(session, str) and bool(session.strip())
    surface = normalize_surface(raw, has_session_pack=has_session)
    if raw and surface is None and not has_session:
        raise SurfaceRequiredError(
            f"Unknown blossom_client {raw!r}; expected companion or assistant."
        )

    pinned = pinned_surface()
    if surface and pinned and surface != pinned:
        raise SurfaceMismatchError(
            f"This ChatRouter serves {pinned}; the request is tagged {surface}. "
            "Point that client at its own router."
        )
    if surface:
        return surface
    if pinned:
        # A dedicated router owns one store, so an untagged call cannot cross over.
        return pinned

    if require_client_tag() if require is None else require:
        raise SurfaceRequiredError(
            "Missing client tag. Send X-Blossom-Client or blossom_client "
            "(companion|assistant)."
        )
    logger.warning("Untagged request routed to the Assistant store (lenient mode).")
    return SURFACE_ASSISTANT


def mind_dir(surface: str) -> Path:
    return MIND_ROOT / _validated(surface)


def db_path(surface: str) -> Path:
    return mind_dir(surface) / _DB_NAMES[_validated(surface)]


def chroma_dir(surface: str) -> Path:
    return mind_dir(surface) / "chromadb"


def legacy_db_path() -> Path:
    return MIND_ROOT / "CompanionMind.db"


def legacy_chroma_dir() -> Path:
    return MIND_ROOT / "chromadb"


@contextlib.contextmanager
def migration_lock(timeout_sec: float = 120.0, stale_sec: float = 600.0) -> Iterator[None]:
    """Cross-process lock so two routers starting together migrate only once."""
    MIND_ROOT.mkdir(parents=True, exist_ok=True)
    lock = MIND_ROOT / ".store-migration.lock"
    deadline = time.monotonic() + timeout_sec
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale_sec:
                    lock.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"Mind store migration lock busy: {lock}")
            time.sleep(0.25)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def migrate_legacy_files() -> dict[str, str]:
    """Move the pre-split Mind layout into per-surface folders (idempotent).

    The legacy SQLite DB becomes Companion's (row-level split happens afterwards in
    MemoryUpdater). The legacy Chroma dir becomes Assistant's, since coding/NLPP
    lessons were its bulk; companion-home collections are copied out afterwards
    in SemanticMemory.
    """
    moved: dict[str, str] = {}
    for surface in SURFACES:
        mind_dir(surface).mkdir(parents=True, exist_ok=True)

    legacy_db = legacy_db_path()
    target_db = db_path(SURFACE_COMPANION)
    if legacy_db.exists() and not target_db.exists():
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(legacy_db) + suffix)
            if src.exists():
                _rename(src, Path(str(target_db) + suffix))
        moved["db"] = str(target_db)
        logger.info("Moved legacy Mind DB → %s", target_db)

    legacy_chroma = legacy_chroma_dir()
    target_chroma = chroma_dir(SURFACE_ASSISTANT)
    if legacy_chroma.is_dir() and not target_chroma.exists():
        _rename(legacy_chroma, target_chroma)
        moved["chroma"] = str(target_chroma)
        logger.info("Moved legacy Chroma store → %s", target_chroma)
    return moved


def _rename(src: Path, dst: Path) -> None:
    """Atomic same-volume move. Never copy+delete: a half-moved store is worse than none."""
    try:
        os.replace(src, dst)
    except PermissionError as exc:
        raise RuntimeError(
            f"Cannot move {src} → {dst}: files are in use. Stop every ChatRouter "
            "(and anything holding the Mind folder) and start again."
        ) from exc
