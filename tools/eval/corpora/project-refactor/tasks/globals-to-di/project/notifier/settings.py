"""Global, mutable settings shared by every module (the thing we want to get rid of)."""
SETTINGS = {
    "sender": "noreply@example.com",
    "sms_prefix": "+1",
    "dry_run": False,
    "max_retries": 2,
}


def configure(**overrides):
    SETTINGS.update(overrides)
