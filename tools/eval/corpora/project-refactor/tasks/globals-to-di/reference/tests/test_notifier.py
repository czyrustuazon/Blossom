from notifier.config import Settings
from notifier.dispatcher import Dispatcher
from notifier.mailer import Mailer
from notifier.sms import SmsSender
from notifier.transport import OutboxTransport


def test_notify_both_channels():
    out = OutboxTransport()
    s = Settings()
    d = Dispatcher(Mailer(s, out), SmsSender(s, out))
    assert d.notify({"email": "a@b.c", "phone": "5551234"}, "hi") == [("email", "sent"), ("sms", "sent")]
    assert out.sent[1] == ("sms", "+15551234", "hi")
    assert out.sent[0][2].startswith("From: noreply@example.com")


def test_retries_and_dry_run():
    assert Mailer(Settings(), OutboxTransport(fail_times=2)).send_email("a@b.c", "s", "b") == "sent"
    assert SmsSender(Settings(dry_run=True), OutboxTransport()).send_sms("1", "x") == "dry-run"
