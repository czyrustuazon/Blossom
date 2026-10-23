"""
Brain broker: the only process that owns llama-server.

Split mode runs one ChatRouter per client (Companion, Assistant). Both need the
same GPU, so neither may hot-swap models on its own. A router takes an exclusive
lease (FIFO, TTL + heartbeat) for the duration of a pipeline — the cross-process
replacement for ChatRouter's in-process swap_lock — and asks the broker to make a
role live with /v1/ensure while holding it.

Endpoints:
  POST /v1/lease/acquire {holder, wait_sec}  -> {lease_id, ttl_sec}   (408 on timeout)
  POST /v1/lease/renew   {lease_id}          -> {ok}                  (410 if lost)
  POST /v1/lease/release {lease_id}          -> {ok}
  POST /v1/ensure        {lease_id, role, model_path?, min_ctx?}      (409 without lease)
  GET  /v1/status
  GET  /health
"""

from __future__ import annotations

import itertools
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
load_dotenv(SCRIPT_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="[Blossom Broker]: %(message)s")
logger = logging.getLogger(__name__)

BROKER_HOST = os.getenv("BLOSSOM_BROKER_HOST", "127.0.0.1")
BROKER_PORT = int(os.getenv("BLOSSOM_BROKER_PORT", "8085"))
LEASE_TTL_SEC = float(os.getenv("BLOSSOM_LEASE_TTL_SEC", "120"))


@dataclass
class Lease:
    lease_id: str
    holder: str
    expires_at: float
    granted_at: float


class LeaseNotHeld(RuntimeError):
    pass


class LeaseManager:
    """One exclusive lease at a time, granted first-come first-served."""

    def __init__(self, ttl_sec: float = LEASE_TTL_SEC, clock=time.monotonic):
        self.ttl_sec = ttl_sec
        self._clock = clock
        self._cond = threading.Condition()
        self._active: Lease | None = None
        self._queue: list[int] = []
        self._tickets = itertools.count()

    def _reap(self) -> None:
        if self._active and self._active.expires_at <= self._clock():
            logger.warning(
                "Lease %s (%s) expired without release — reclaiming",
                self._active.lease_id,
                self._active.holder,
            )
            self._active = None
            self._cond.notify_all()

    def acquire(self, holder: str, wait_sec: float) -> Lease | None:
        deadline = self._clock() + max(0.0, wait_sec)
        with self._cond:
            ticket = next(self._tickets)
            self._queue.append(ticket)
            try:
                while True:
                    self._reap()
                    if self._active is None and self._queue[0] == ticket:
                        now = self._clock()
                        self._active = Lease(
                            lease_id=str(uuid.uuid4()),
                            holder=holder,
                            expires_at=now + self.ttl_sec,
                            granted_at=now,
                        )
                        return self._active
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        return None
                    # Wake periodically so an expired holder is reaped without a release.
                    self._cond.wait(timeout=min(remaining, 1.0))
            finally:
                self._queue.remove(ticket)
                self._cond.notify_all()

    def check(self, lease_id: str) -> Lease:
        with self._cond:
            self._reap()
            if not self._active or self._active.lease_id != lease_id:
                raise LeaseNotHeld(lease_id)
            return self._active

    def renew(self, lease_id: str) -> Lease:
        with self._cond:
            lease = self.check(lease_id)
            lease.expires_at = self._clock() + self.ttl_sec
            return lease

    def release(self, lease_id: str) -> bool:
        with self._cond:
            if self._active and self._active.lease_id == lease_id:
                self._active = None
                self._cond.notify_all()
                return True
            return False

    def snapshot(self) -> dict[str, Any]:
        with self._cond:
            self._reap()
            active = self._active
            return {
                "holder": active.holder if active else None,
                "held_for_sec": round(self._clock() - active.granted_at, 1) if active else None,
                "waiting": len(self._queue),
            }


leases = LeaseManager()
_ensure_lock = threading.Lock()
_manager = None


def _server_manager():
    global _manager
    if _manager is None:
        from LlamaServerManager import server_manager

        _manager = server_manager
    return _manager


def _status() -> dict[str, Any]:
    manager = _server_manager()
    return {
        "ok": True,
        "role": manager.current_role,
        "model": str(manager.current_model) if manager.current_model else None,
        "ctx": manager.current_ctx,
        "healthy": manager.is_healthy(),
        "lease": leases.snapshot(),
    }


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.getenv("BLOSSOM_BROKER_BOOT_ROLE", "persona").strip().lower() == "persona":
        logger.info("Booting persona llama-server…")
        with _ensure_lock:
            _server_manager().ensure("persona")
    try:
        yield
    finally:
        logger.info("Stopping llama-server…")
        with _ensure_lock:
            _server_manager().stop()


app = FastAPI(title="Blossom Brain Broker", lifespan=lifespan)


class AcquireBody(BaseModel):
    holder: str = "unknown"
    wait_sec: float = 600.0


class LeaseBody(BaseModel):
    lease_id: str


class EnsureBody(BaseModel):
    lease_id: str
    role: str
    model_path: str | None = None
    min_ctx: int = 0


@app.post("/v1/lease/acquire")
def acquire(body: AcquireBody):
    lease = leases.acquire(body.holder, min(body.wait_sec, 3600.0))
    if lease is None:
        raise HTTPException(status_code=408, detail="Timed out waiting for the model lease")
    logger.info("Lease → %s", lease.holder)
    return {"ok": True, "lease_id": lease.lease_id, "ttl_sec": leases.ttl_sec}


@app.post("/v1/lease/renew")
def renew(body: LeaseBody):
    try:
        lease = leases.renew(body.lease_id)
    except LeaseNotHeld:
        raise HTTPException(status_code=410, detail="Lease is no longer held")
    return {"ok": True, "expires_in_sec": round(lease.expires_at - time.monotonic(), 1)}


@app.post("/v1/lease/release")
def release(body: LeaseBody):
    return {"ok": True, "released": leases.release(body.lease_id)}


@app.post("/v1/ensure")
def ensure(body: EnsureBody):
    role = body.role.strip().lower()
    if role not in {"persona", "coder"}:
        raise HTTPException(status_code=400, detail="role must be persona or coder")
    try:
        leases.check(body.lease_id)
    except LeaseNotHeld:
        raise HTTPException(status_code=409, detail="Hold the model lease before /v1/ensure")
    with _ensure_lock:
        _server_manager().ensure(
            role,
            model_path=Path(body.model_path) if body.model_path else None,
            min_ctx=max(0, int(body.min_ctx)),
        )
    return _status()


@app.get("/v1/status")
def status():
    return _status()


@app.get("/health")
def health():
    return {"ok": True, "lease": leases.snapshot()}


if __name__ == "__main__":
    uvicorn.run(app, host=BROKER_HOST, port=BROKER_PORT)
