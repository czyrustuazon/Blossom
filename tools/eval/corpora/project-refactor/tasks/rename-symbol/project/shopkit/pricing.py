from decimal import Decimal, ROUND_HALF_UP


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calc_total(items, tax_rate=0.0):
    """Sum (price * qty) for items and add tax. Returns Decimal rounded to cents."""
    subtotal = sum(Decimal(str(i["price"])) * i.get("qty", 1) for i in items)
    return _money(subtotal * (1 + Decimal(str(tax_rate))))


def apply_discount(total, percent):
    return _money(Decimal(total) * (1 - Decimal(str(percent)) / 100))
