from decimal import Decimal

from shopkit import Cart, calc_total
from shopkit.checkout import checkout
from shopkit.reports import daily_report


def test_calc_total_with_tax():
    assert calc_total([{"price": 10, "qty": 2}], 0.1) == Decimal("22.00")


def test_cart_and_checkout():
    c = Cart(tax_rate=0.05)
    c.add("pen", 1.5, 4)
    assert c.total() == Decimal("6.30")
    assert checkout(c, coupon_percent=10) == Decimal("5.67")


def test_report():
    assert daily_report([[{"price": 1}], [{"price": 2, "qty": 3}]]) == (2, Decimal("7.00"))
