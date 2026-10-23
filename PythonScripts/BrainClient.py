"""
ChatRouter side of the brain broker (see BrainBroker.py).

BrainLease replaces the in-process swap_lock: `with swap_lock:` takes the
cross-process model lease and keeps it alive with a heartbeat. RemoteServerManager
replaces LlamaServerManager.server_manager: ensure() goes through the broker.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)


class BrainBrokerError(RuntimeError):
    pass


class BrainLease:
    """Reentrant, process-wide model lease used like a lock."""

    def __init__(
        self,
        base_url: str,
        *,
        holder: str,
        wait_sec: float = 900.0,
        request_timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.holder = holder
        self.wait_sec = wait_sec
        self.request_timeout = request_timeout
        # Serializes this process's pipelines, exactly like the old swap_lock.
        self._local = threading.RLock()
        self._depth = 0
        self._lease_id: str | None = None
        self._stop_heartbeat: threading.Event | None = None

    @property
    def current_id(self) -> str | None:
        """Lease id held by this process right now (any thread), if any."""
        return self._lease_id

    def _post(self, path: str, payload: dict[str, Any], timeout: float) -> requests.Response:
        try:
            return requests.post(f"{self.base_url}{path}", json=payload, timeout=timeout)
        except requests.RequestException as exc:
            raise BrainBrokerError(f"Brain broker unreachable at {self.base_url}: {exc}") from exc

    def _acquire_remote(self) -> None:
        deadline = time.monotonic() + self.wait_sec
        while True:
            wait = max(1.0, min(300.0, deadline - time.monotonic()))
            resp = self._post(
                "/v1/lease/acquire",
                {"holder": self.holder, "wait_sec": wait},
                timeout=wait + self.request_timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                self._lease_id = data["lease_id"]
                self._start_heartbeat(float(data.get("ttl_sec") or 120.0))
                return
            if resp.status_code == 408 and time.monotonic() < deadline:
                continue
            raise BrainBrokerError(f"Lease acquire failed ({resp.status_code}): {resp.text}")

    def _start_heartbeat(self, ttl_sec: float) -> None:
        stop = threading.Event()
        self._stop_heartbeat = stop
        lease_id = self._lease_id
        interval = max(1.0, ttl_sec / 3)

        def beat() -> None:
            while not stop.wait(interval):
                try:
                    resp = self._post(
                        "/v1/lease/renew", {"lease_id": lease_id}, timeout=self.request_timeout
                    )
                    if resp.status_code == 410:
                        logger.error("Brain lease %s was lost (expired on the broker)", lease_id)
                        return
                except BrainBrokerError as exc:
                    logger.warning("Brain lease heartbeat failed: %s", exc)

        threading.Thread(target=beat, daemon=True, name="brain-lease-heartbeat").start()

    def _release_remote(self) -> None:
        if self._stop_heartbeat:
            self._stop_heartbeat.set()
            self._stop_heartbeat = None
        lease_id, self._lease_id = self._lease_id, None
        if lease_id:
            try:
                self._post("/v1/lease/release", {"lease_id": lease_id}, timeout=self.request_timeout)
            except BrainBrokerError as exc:
                logger.warning("Brain lease release failed (it will expire): %s", exc)

    def __enter__(self) -> "BrainLease":
        self._local.acquire()
        try:
            if self._depth == 0:
                self._acquire_remote()
            self._depth += 1
        except BaseException:
            self._local.release()
            raise
        return self

    def __exit__(self, *_exc) -> None:
        try:
            self._depth -= 1
            if self._depth == 0:
                self._release_remote()
        finally:
            self._local.release()


class RemoteServerManager:
    """Drop-in for LlamaServerManager when the broker owns llama-server."""

    def __init__(self, base_url: str, lease: BrainLease, *, status_ttl: float = 0.5):
        self.base_url = base_url.rstrip("/")
        self.lease = lease
        self._status_ttl = status_ttl
        self._status: dict[str, Any] = {}
        self._status_at = 0.0

    def _remember(self, data: dict[str, Any]) -> dict[str, Any]:
        self._status = data
        self._status_at = time.monotonic()
        return data

    def status(self, *, fresh: bool = False) -> dict[str, Any]:
        if not fresh and time.monotonic() - self._status_at < self._status_ttl:
            return self._status
        try:
            resp = requests.get(f"{self.base_url}/v1/status", timeout=5)
            resp.raise_for_status()
            return self._remember(resp.json())
        except requests.RequestException as exc:
            logger.warning("Brain broker status failed: %s", exc)
            return self._remember({"ok": False})

    def ensure(self, role: str, model_path: Path | None = None, *, min_ctx: int = 0) -> None:
        if self.lease.current_id:
            self._ensure(self.lease.current_id, role, model_path, min_ctx)
            return
        with self.lease:
            self._ensure(self.lease.current_id, role, model_path, min_ctx)

    def _ensure(self, lease_id: str | None, role: str, model_path: Path | None, min_ctx: int) -> None:
        payload = {
            "lease_id": lease_id,
            "role": role,
            "model_path": str(model_path) if model_path else None,
            "min_ctx": int(min_ctx or 0),
        }
        try:
            resp = requests.post(f"{self.base_url}/v1/ensure", json=payload, timeout=900)
        except requests.RequestException as exc:
            raise BrainBrokerError(f"Brain broker ensure failed: {exc}") from exc
        if resp.status_code != 200:
            raise BrainBrokerError(f"Brain broker ensure {role} failed ({resp.status_code}): {resp.text}")
        self._remember(resp.json())

    @property
    def current_role(self) -> str | None:
        return self.status().get("role")

    @property
    def current_model(self) -> Path | None:
        model = self.status().get("model")
        return Path(model) if model else None

    @property
    def current_ctx(self) -> int | None:
        return self.status().get("ctx")

    def is_healthy(self, timeout: float = 2.0) -> bool:
        return bool(self.status(fresh=True).get("healthy"))

    def coder_available(self) -> bool:
        from LocalModels import any_coder_available

        return any_coder_available()

    def stop(self) -> None:
        """The broker owns llama-server's lifetime; routers never stop it."""
