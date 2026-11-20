from .pricing import compute_order_total as _total


def daily_report(orders):
    """orders: list of item lists. Returns (count, grand_total)."""
    grand = sum((_total(o) for o in orders), start=_total([]))
    return len(orders), grand
