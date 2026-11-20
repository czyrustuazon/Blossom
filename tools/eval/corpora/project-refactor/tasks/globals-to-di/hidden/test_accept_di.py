import ast
import pathlib

import pytest

from notifier.config import Settings
from notifier.dispatcher import Dispatcher
from notifier.mailer import Mailer
from notifier.sms import SmsSender
from notifier.transport import OutboxTransport


def test_no_global_state_left():
    pkg = pathlib.Path("notifier")
    assert not (pkg / "settings.py").exists(), "old global settings module must be removed"
    for path in pkg.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(isinstance(n, ast.Global) for n in ast.walk(tree)), path
        assert "SETTINGS" not in path.read_text(encoding="utf-8"), path


def test_defaults():
    s = Settings()
    assert (s.sender, s.sms_prefix, s.dry_run, s.max_retries) == ("noreply@example.com", "+1", False, 2)


def test_injected_instances_are_independent():
    out_a, out_b = OutboxTransport(), OutboxTransport()
    a = Dispatcher(Mailer(Settings(sender="a@x.io"), out_a), SmsSender(Settings(), out_a))
    b = Dispatcher(Mailer(Settings(), out_b), SmsSender(Settings(sms_prefix="+44", dry_run=True), out_b))
    assert a.notify({"email": "u@v.w", "phone": "5551234"}, "hi") == [("email", "sent"), ("sms", "sent")]
    assert out_a.sent[0][2].startswith("From: a@x.io")
    assert out_a.sent[1] == ("sms", "+15551234", "hi")
    assert b.notify({"email": "u@v.w", "phone": "77"}, "yo") == [("email", "sent"), ("sms", "dry-run")]
    assert [m[0] for m in out_b.sent] == ["email"]


def test_retries_respect_settings():
    m = Mailer(Settings(max_retries=2), OutboxTransport(fail_times=2))
    assert m.send_email("a@b.c", "s", "b") == "sent"
    with pytest.raises(ConnectionError):
        Mailer(Settings(max_retries=0), OutboxTransport(fail_times=1)).send_email("a@b.c", "s", "b")
