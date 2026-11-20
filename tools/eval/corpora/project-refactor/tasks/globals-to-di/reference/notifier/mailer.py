class Mailer:
    def __init__(self, settings, transport):
        self.settings = settings
        self.transport = transport

    def send_email(self, to, subject, body):
        if self.settings.dry_run:
            return "dry-run"
        last = None
        for _ in range(self.settings.max_retries + 1):
            try:
                self.transport.send(
                    "email", to, f"From: {self.settings.sender}\nSubject: {subject}\n\n{body}"
                )
                return "sent"
            except ConnectionError as exc:
                last = exc
        raise last
