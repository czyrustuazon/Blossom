from . import mailer, sms


def notify(user, message):
    """user: dict with optional 'email' and 'phone'. Returns list of channel results."""
    results = []
    if user.get("email"):
        results.append(("email", mailer.send_email(user["email"], "Notice", message)))
    if user.get("phone"):
        results.append(("sms", sms.send_sms(user["phone"], message)))
    return results
