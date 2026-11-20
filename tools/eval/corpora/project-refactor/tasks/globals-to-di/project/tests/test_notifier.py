import pytest

from notifier import mailer, sms
from notifier.dispatcher import notify
from notifier.settings import SETTINGS, configure
from notifier.transport import OutboxTransport


@pytest.fixture(autouse=True)
def reset():
    saved = dict(SETTINGS)
    yield
    SETTINGS.clear()
    SETTINGS.update(saved)


def test_notify_both_channels():
    out = OutboxTransport()
    mailer.set_transport(out)
    sms.set_transport(out)
    assert notify({"email": "a@b.c", "phone": "5551234"}, "hi") == [("email", "sent"), ("sms", "sent")]
    assert out.sent[1] == ("sms", "+15551234", "hi")
    assert out.sent[0][2].startswith("From: noreply@example.com")


def test_retries_and_dry_run():
    out = OutboxTransport(fail_times=2)
    mailer.set_transport(out)
    assert mailer.send_email("a@b.c", "s", "b") == "sent"
    configure(dry_run=True)
    assert sms.send_sms("1", "x") == "dry-run"
