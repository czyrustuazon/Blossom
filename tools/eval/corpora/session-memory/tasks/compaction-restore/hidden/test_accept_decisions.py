"""Acceptance: both settings decisions from turn 1 were applied, and nothing else moved."""

from netclient import config
from netclient.client import Client, FetchError


def test_max_retries_is_seven():
    assert config.MAX_RETRIES == 7


def test_user_agent_is_agreed_value():
    assert config.USER_AGENT == "blossom-probe/2.4"


def test_client_uses_new_values():
    calls = []

    def transport(url, headers):
        calls.append(headers)
        return (503, "")

    client = Client(transport, sleep=lambda s: None)
    try:
        client.fetch("/x")
    except FetchError:
        pass
    assert len(calls) == 7
    assert all(h["User-Agent"] == "blossom-probe/2.4" for h in calls)


def test_other_settings_unchanged():
    assert config.BACKOFF_SECONDS == 0.5
    assert config.CACHE_TTL_SECONDS == 300
