from .settings import SETTINGS

_transport = None


def set_transport(transport):
    global _transport
    _transport = transport


def send_email(to, subject, body):
    if SETTINGS["dry_run"]:
        return "dry-run"
    last = None
    for _ in range(SETTINGS["max_retries"] + 1):
        try:
            _transport.send("email", to, f"From: {SETTINGS['sender']}\nSubject: {subject}\n\n{body}")
            return "sent"
        except ConnectionError as exc:
            last = exc
    raise last
