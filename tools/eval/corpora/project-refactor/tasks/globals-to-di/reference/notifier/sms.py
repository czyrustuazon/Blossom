class SmsSender:
    def __init__(self, settings, transport):
        self.settings = settings
        self.transport = transport

    def send_sms(self, number, text):
        if self.settings.dry_run:
            return "dry-run"
        if not number.startswith("+"):
            number = self.settings.sms_prefix + number
        self.transport.send("sms", number, text[:160])
        return "sent"
