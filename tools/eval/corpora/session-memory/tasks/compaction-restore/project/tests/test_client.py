import pytest

from netclient import config
from netclient.cache import ResponseCache
from netclient.client import Client, FetchError


def make_transport(responses):
    calls = []

    def transport(url, headers):
        calls.append((url, headers))
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    transport.calls = calls
    return transport


def make_client(responses):
    transport = make_transport(responses)
    sleeps = []
    return Client(transport, sleep=sleeps.append), transport, sleeps


def test_success_is_cached():
    client, transport, _ = make_client([(200, "ok")])
    assert client.fetch("/a") == "ok"
    assert client.fetch("/a") == "ok"
    assert len(transport.calls) == 1


def test_retries_5xx_then_succeeds():
    client, transport, sleeps = make_client([(503, ""), (200, "ok")])
    assert client.fetch("/a") == "ok"
    assert len(transport.calls) == 2
    assert sleeps == [config.BACKOFF_SECONDS]


def test_retries_oserror():
    client, transport, _ = make_client([OSError("reset"), (200, "ok")])
    assert client.fetch("/a") == "ok"
    assert len(transport.calls) == 2


def test_gives_up_after_max_retries():
    client, transport, sleeps = make_client([(500, "")] * config.MAX_RETRIES)
    with pytest.raises(FetchError):
        client.fetch("/a")
    assert len(transport.calls) == config.MAX_RETRIES
    assert len(sleeps) == config.MAX_RETRIES - 1


def test_4xx_is_not_retried():
    client, transport, _ = make_client([(404, "")])
    with pytest.raises(FetchError):
        client.fetch("/a")
    assert len(transport.calls) == 1


def test_sends_configured_user_agent():
    client, transport, _ = make_client([(200, "ok")])
    client.fetch("/a")
    assert transport.calls[0][1]["User-Agent"] == config.USER_AGENT


def test_cache_expires():
    now = [0.0]
    cache = ResponseCache(ttl=10, clock=lambda: now[0])
    cache.put("k", "v")
    now[0] = 5
    assert cache.get("k") == "v"
    now[0] = 11
    assert cache.get("k") is None
