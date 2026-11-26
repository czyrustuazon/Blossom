"""Per-request coder choice (`blossom_coder`) and stopping a request whose client left.

The cancel tests come from the q38-fen3 callbacks-to-async stall (2026-11-24): the host aborted
round 1, the router kept decoding it while holding the brain lease, and round 2 got 0 bytes for
243 s until the host's stall watchdog ended the turn.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ChatRouter  # noqa: E402
from LocalModels import (  # noqa: E402
    LocalModel,
    coder_label,
    coder_notes,
    coder_tool_mode,
    match_coder,
    order_ladder,
)

Q38 = LocalModel(Path("C:/m/coding/Qwen3.8-27B-UD-Q4_K_M.gguf"), "coder")
Q36 = LocalModel(Path("C:/m/coding/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"), "coder")
NEMO = LocalModel(Path("C:/m/coding/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-IQ4_XS.gguf"), "coder")
LADDER = [Q38, Q36, NEMO]


# --- coder catalog ------------------------------------------------------------


def test_tool_modes_follow_the_eval_results():
    assert coder_tool_mode(Q38.path) == "fence"
    assert coder_tool_mode(Q36.path) == "native"
    assert coder_tool_mode(NEMO.path) == "fence"
    assert coder_tool_mode(Path("Other.gguf")) == "fence"
    assert coder_tool_mode(Q38.path, rules="Qwen3.8=native") == "native"


def test_labels():
    assert coder_label(Q38.path) == "Qwen3.8 27B"
    assert coder_label(NEMO.path) == "Nemotron 3.5 Lightning 30B"


def test_notes_say_what_each_coder_is_good_at():
    assert coder_notes(Q38.path, rules="")[0] == "most accurate · slower"
    assert coder_notes(Q36.path, rules="")[0] == "fast · good accuracy · best for 256k"
    assert "long context" in coder_notes(NEMO.path, rules="")[0]
    assert "93%" in coder_notes(Q38.path, rules="")[1]
    assert coder_notes(Path("Other.gguf"), rules="") == ("", "")
    # CODER_NOTES overrides: "needle=short|long"; short alone doubles as the note.
    assert coder_notes(Q38.path, rules="Qwen3.8=my pick|Why I use it") == ("my pick", "Why I use it")
    assert coder_notes(NEMO.path, rules="Nemotron=logs only") == ("logs only", "logs only")


def test_session_budget_follows_the_coder_window():
    """A 64k coder gets a 64k-sized session budget, not the fixed 200k one."""
    share = ChatRouter.SESSION_CONTEXT_SHARE
    cap = ChatRouter.SESSION_CONTEXT_BUDGET
    assert ChatRouter._session_budget_for_ctx(65536) == min(cap, int(65536 * share))
    assert ChatRouter._session_budget_for_ctx(65536) < 65536 // 2
    assert ChatRouter._session_budget_for_ctx(10_000_000) == cap
    assert ChatRouter._session_budget_for_ctx(1000) == 1024


def test_coder_max_ctx_is_the_largest_profile():
    with patch.object(ChatRouter, "profiles_for_model",
                      lambda _p: [SimpleNamespace(ctx=65536), SimpleNamespace(ctx=262144)]):
        assert ChatRouter._coder_max_ctx(Path("C:/nowhere/x.gguf")) == 262144
    with patch.object(ChatRouter, "profiles_for_model", lambda _p: [SimpleNamespace(ctx=65536)]):
        assert ChatRouter._coder_max_ctx(Path("C:/nowhere/x.gguf")) == 65536


def test_session_ctx_can_stay_below_a_slow_largest_profile():
    with patch.object(ChatRouter, "profiles_for_model",
                      lambda _p: [SimpleNamespace(ctx=65536), SimpleNamespace(ctx=262144)]):
        path = Path("C:/nowhere/Qwen3.8-27B-UD-Q4_K_M.gguf")
        assert ChatRouter._coder_session_ctx(path, rules="Qwen3.8=131072") == 131072
        assert ChatRouter._coder_session_ctx(path, rules="Nemotron=65536") == 262144
        assert ChatRouter._coder_session_ctx(path, rules="Qwen3.8=999999") == 262144  # never above max
        assert ChatRouter._coder_session_ctx(path, rules="") == 262144


def test_choice_by_id_file_or_unique_substring():
    assert match_coder("qwen3.6-35b-a3b-ud-q4_k_m", LADDER) is Q36
    assert match_coder("NVIDIA-Nemotron-3.5-Lightning-30B-A3B-IQ4_XS.gguf", LADDER) is NEMO
    assert match_coder("nemotron", LADDER) is NEMO
    assert match_coder("qwen", LADDER) is None  # ambiguous
    assert match_coder("", LADDER) is None


def test_chosen_coder_goes_first_and_the_rest_stay_as_fallbacks():
    assert order_ladder(LADDER, "nemotron") == [NEMO, Q38, Q36]
    assert order_ladder(LADDER, "unknown") == LADDER
    assert order_ladder(LADDER, "") == LADDER


def test_request_choice_reorders_the_router_ladder():
    token = ChatRouter._CODER_CHOICE_CV.set("qwen3.6")
    try:
        with patch.object(ChatRouter, "coder_ladder", lambda available_only=False: list(LADDER)):
            assert ChatRouter._coder_ladder()[0] is Q36
    finally:
        ChatRouter._CODER_CHOICE_CV.reset(token)


# --- cancel on client disconnect ---------------------------------------------


class _Stream:
    """Fake llama-server stream: one content delta per chunk, records close()."""

    def __init__(self, n: int, on_chunk=None):
        self.n = n
        self.on_chunk = on_chunk
        self.closed = False
        self.sent = 0

    def __iter__(self):
        for i in range(self.n):
            if self.closed:
                return
            self.sent += 1
            if self.on_chunk:
                self.on_chunk(i)
            delta = SimpleNamespace(content="tok ", reasoning_content=None, tool_calls=None)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=None)])

    def close(self):
        self.closed = True


def _client_returning(stream):
    create = lambda **_kw: stream  # noqa: E731
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_decode_stops_and_closes_upstream_when_the_client_leaves():
    cancel = threading.Event()
    stream = _Stream(1000, on_chunk=lambda i: cancel.set() if i == 5 else None)
    token = ChatRouter._CANCEL_CV.set(cancel)
    try:
        with patch.object(ChatRouter, "LOCAL_CLIENT", _client_returning(stream)):
            with pytest.raises(ChatRouter.RequestCancelled):
                ChatRouter._stream_local_chat(
                    [{"role": "user", "content": "hi"}], model="m", temperature=0.6
                )
    finally:
        ChatRouter._CANCEL_CV.reset(token)
    assert stream.closed
    assert stream.sent < 10


def test_cancel_is_not_an_ordinary_exception():
    # Generic `except Exception` fallbacks (next coder, sequential mode) must not swallow it.
    assert not issubclass(ChatRouter.RequestCancelled, Exception)


def test_no_cancel_event_streams_normally():
    stream = _Stream(3)
    with patch.object(ChatRouter, "LOCAL_CLIENT", _client_returning(stream)):
        out = ChatRouter._stream_local_chat(
            [{"role": "user", "content": "hi"}], model="m", temperature=0.6
        )
    assert out.strip() == "tok tok tok"


def test_stream_asks_for_usage_and_reports_it_as_a_thought():
    """llama-server's final usage chunk (no choices) becomes one token_usage thought."""
    seen_kwargs: dict = {}

    def chunks():
        delta = SimpleNamespace(content="ok", reasoning_content=None, tool_calls=None)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason="stop")], usage=None)
        yield SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=1200, completion_tokens=345))

    def create(**kw):
        seen_kwargs.update(kw)
        return chunks()

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    events: list[dict] = []
    meta: dict = {}
    with patch.object(ChatRouter, "LOCAL_CLIENT", client):
        out = ChatRouter._stream_local_chat(
            [{"role": "user", "content": "hi"}], model="m", temperature=0.6,
            on_progress=events.append, meta=meta,
        )
    assert out.strip() == "ok"
    assert seen_kwargs["stream_options"] == {"include_usage": True}
    usage = [e for e in events if e["step"] == "token_usage"]
    assert len(usage) == 1
    assert usage[0]["prompt_tokens"] == 1200 and usage[0]["completion_tokens"] == 345
    assert meta["usage"] == {"prompt_tokens": 1200, "completion_tokens": 345}


def test_stream_without_usage_sends_no_token_thought():
    events: list[dict] = []
    with patch.object(ChatRouter, "LOCAL_CLIENT", _client_returning(_Stream(2))):
        ChatRouter._stream_local_chat(
            [{"role": "user", "content": "hi"}], model="m", temperature=0.6, on_progress=events.append
        )
    assert not [e for e in events if e["step"] == "token_usage"]


def test_waiting_request_says_so_and_skips_work_if_its_client_left():
    lock = threading.Lock()
    events: list[dict] = []
    cancel = threading.Event()
    lock.acquire()  # another request holds the brain

    def release_later():
        time.sleep(0.4)
        cancel.set()  # this client gave up while waiting
        lock.release()

    threading.Thread(target=release_later, daemon=True).start()
    token = ChatRouter._CANCEL_CV.set(cancel)
    try:
        with patch.object(ChatRouter, "swap_lock", lock), patch.object(
            ChatRouter, "LEASE_WAIT_NOTICE_SEC", 0.05
        ):
            with pytest.raises(ChatRouter.RequestCancelled):
                with ChatRouter._lease_for_request(events.append):
                    pytest.fail("work ran for a request whose client already left")
    finally:
        ChatRouter._CANCEL_CV.reset(token)
    assert [e["step"] for e in events] == ["lease_wait"]
    assert not lock.locked()


def test_free_lease_gives_no_wait_notice():
    events: list[dict] = []
    with patch.object(ChatRouter, "swap_lock", threading.Lock()), patch.object(
        ChatRouter, "LEASE_WAIT_NOTICE_SEC", 0.05
    ):
        with ChatRouter._lease_for_request(events.append):
            time.sleep(0.15)
    assert events == []
