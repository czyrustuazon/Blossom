from .settings import SETTINGS

_transport = None


def set_transport(transport):
    global _transport
    _transport = transport


def send_sms(number, text):
    if SETTINGS["dry_run"]:
        return "dry-run"
    if not number.startswith("+"):
        number = SETTINGS["sms_prefix"] + number
    _transport.send("sms", number, text[:160])
    return "sent"
