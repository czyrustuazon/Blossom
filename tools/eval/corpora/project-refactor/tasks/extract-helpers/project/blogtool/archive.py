from datetime import date, datetime


def _parse_date(value):
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"bad date: {value!r}")


def posts_between(posts, start, end):
    lo, hi = _parse_date(start), _parse_date(end)
    return [p for p in posts if lo <= p.published <= hi]
