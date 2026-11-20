from . import pricing
from .pricing import apply_discount


def checkout(cart, coupon_percent=0):
    """Return the amount to charge for a cart, after an optional coupon."""
    gross = pricing.calc_total(cart.items, cart.tax_rate)
    if coupon_percent:
        return apply_discount(gross, coupon_percent)
    return gross
