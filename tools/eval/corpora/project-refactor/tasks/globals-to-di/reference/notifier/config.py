from dataclasses import dataclass


@dataclass
class Settings:
    sender: str = "noreply@example.com"
    sms_prefix: str = "+1"
    dry_run: bool = False
    max_retries: int = 2
