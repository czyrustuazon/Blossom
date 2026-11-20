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


class Post:
    def __init__(self, title, published, body=""):
        self.title = title
        self.slug = _slugify(title)
        self.published = _parse_date(published)
        self.body = body

    def url(self):
        return f"/{self.published:%Y/%m}/{self.slug}/"
