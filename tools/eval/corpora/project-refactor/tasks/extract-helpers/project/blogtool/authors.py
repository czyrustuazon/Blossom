import re
from datetime import date, datetime


def _slugify(text):
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    return re.sub(r"[\s-]+", "-", text).strip("-")


def _parse_date(value):
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"bad date: {value!r}")


class Author:
    def __init__(self, name, joined):
        self.name = name
        self.handle = _slugify(name)
        self.joined = _parse_date(joined)

    def profile_url(self):
        return f"/authors/{self.handle}/"
