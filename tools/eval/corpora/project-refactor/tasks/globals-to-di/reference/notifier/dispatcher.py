class Dispatcher:
    def __init__(self, mailer, sms):
        self.mailer = mailer
        self.sms = sms

    def notify(self, user, message):
        """user: dict with optional 'email' and 'phone'. Returns list of channel results."""
        results = []
        if user.get("email"):
            results.append(("email", self.mailer.send_email(user["email"], "Notice", message)))
        if user.get("phone"):
            results.append(("sms", self.sms.send_sms(user["phone"], message)))
        return results
