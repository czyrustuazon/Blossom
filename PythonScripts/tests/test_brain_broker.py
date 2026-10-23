"""Brain broker: exclusive FIFO model lease shared by the split ChatRouters."""

from __future__ import annotations

import socket
import sys
import threading
import time
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import uvicorn  # noqa: E402

import BrainBroker  # noqa: E402
from BrainBroker import LeaseManager, LeaseNotHeld  # noqa: E402
from BrainClient import BrainLease, RemoteServerManager  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class LeaseManagerTests(unittest.TestCase):
    def test_exclusive_until_released(self):
        mgr = LeaseManager(ttl_sec=60)
        first = mgr.acquire("companion", wait_sec=1)
        self.assertIsNotNone(first)
        self.assertIsNone(mgr.acquire("assistant", wait_sec=0.2))
        mgr.release(first.lease_id)
        self.assertIsNotNone(mgr.acquire("assistant", wait_sec=0.2))

    def test_expired_lease_is_reclaimed(self):
        clock = FakeClock()
        mgr = LeaseManager(ttl_sec=10, clock=clock)
        stale = mgr.acquire("crashed-router", wait_sec=0)
        clock.now += 11
        fresh = mgr.acquire("assistant", wait_sec=0)
        self.assertIsNotNone(fresh)
        with self.assertRaises(LeaseNotHeld):
            mgr.check(stale.lease_id)

    def test_renew_extends_expiry(self):
        clock = FakeClock()
        mgr = LeaseManager(ttl_sec=10, clock=clock)
        lease = mgr.acquire("companion", wait_sec=0)
        clock.now += 8
        mgr.renew(lease.lease_id)
        clock.now += 8
        self.assertEqual(mgr.check(lease.lease_id).holder, "companion")

    def test_fifo_order(self):
        mgr = LeaseManager(ttl_sec=60)
        held = mgr.acquire("first", wait_sec=0)
        order: list[str] = []

        def waiter(name: str, delay: float):
            time.sleep(delay)
            lease = mgr.acquire(name, wait_sec=5)
            order.append(name)
            time.sleep(0.05)
            mgr.release(lease.lease_id)

        threads = [
            threading.Thread(target=waiter, args=("second", 0.0)),
            threading.Thread(target=waiter, args=("third", 0.1)),
        ]
        for t in threads:
            t.start()
        time.sleep(0.3)
        mgr.release(held.lease_id)
        for t in threads:
            t.join(timeout=5)
        self.assertEqual(order, ["second", "third"])


class FakeServerManager:
    def __init__(self):
        self.current_role = None
        self.current_model = None
        self.current_ctx = None
        self.calls: list[tuple[str, int]] = []
        self.stopped = False

    def ensure(self, role, model_path=None, *, min_ctx=0):
        self.calls.append((role, min_ctx))
        self.current_role = role
        self.current_model = Path(model_path or f"C:/models/{role}.gguf")
        self.current_ctx = max(min_ctx, 16384)

    def is_healthy(self, timeout=2.0):
        return self.current_role is not None

    def stop(self):
        self.stopped = True
        self.current_role = None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveBrokerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeServerManager()
        BrainBroker._manager = cls.fake
        BrainBroker.leases = LeaseManager(ttl_sec=30)
        port = _free_port()
        cls.url = f"http://127.0.0.1:{port}"
        config = uvicorn.Config(BrainBroker.app, host="127.0.0.1", port=port, log_level="warning")
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 15
        while not cls.server.started and time.time() < deadline:
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)
        BrainBroker._manager = None

    def test_boot_role_is_persona(self):
        self.assertEqual(self.fake.calls[0][0], "persona")

    def test_two_routers_take_turns(self):
        companion = BrainLease(self.url, holder="companion", wait_sec=10)
        assistant = BrainLease(self.url, holder="assistant", wait_sec=10)
        events: list[str] = []

        def assistant_turn():
            with assistant:
                events.append("assistant-start")
                RemoteServerManager(self.url, assistant).ensure("coder", min_ctx=32768)
                events.append("assistant-end")

        with companion:
            events.append("companion-start")
            t = threading.Thread(target=assistant_turn)
            t.start()
            time.sleep(0.5)
            self.assertNotIn("assistant-start", events)
            RemoteServerManager(self.url, companion).ensure("persona")
            events.append("companion-end")
        t.join(timeout=10)
        self.assertEqual(
            events, ["companion-start", "companion-end", "assistant-start", "assistant-end"]
        )
        self.assertEqual(self.fake.current_role, "coder")

    def test_ensure_without_lease_auto_leases(self):
        lease = BrainLease(self.url, holder="auto", wait_sec=10)
        remote = RemoteServerManager(self.url, lease)
        remote.ensure("persona")
        self.assertIsNone(lease.current_id)
        self.assertEqual(remote.current_role, "persona")

    def test_ensure_with_foreign_lease_is_refused(self):
        import requests

        resp = requests.post(
            f"{self.url}/v1/ensure", json={"lease_id": "not-mine", "role": "coder"}, timeout=5
        )
        self.assertEqual(resp.status_code, 409)

    def test_nested_with_reuses_one_lease(self):
        lease = BrainLease(self.url, holder="nested", wait_sec=10)
        with lease:
            first = lease.current_id
            with lease:
                self.assertEqual(lease.current_id, first)
            self.assertEqual(lease.current_id, first)
        self.assertIsNone(lease.current_id)
