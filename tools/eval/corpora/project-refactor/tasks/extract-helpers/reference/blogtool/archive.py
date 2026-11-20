from .textutil import parse_date


def posts_between(posts, start, end):
    lo, hi = parse_date(start), parse_date(end)
    return [p for p in posts if lo <= p.published <= hi]
