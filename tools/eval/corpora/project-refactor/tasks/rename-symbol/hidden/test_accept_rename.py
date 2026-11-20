import pathlib
from decimal import Decimal

import shopkit
from shopkit import Cart, compute_order_total
from shopkit.checkout import checkout
from shopkit.pricing import compute_order_total as direct
from shopkit.reports import daily_report


def test_new_name_works():
    assert compute_order_total is direct
    assert compute_order_total([{"price": 10, "qty": 2}], 0.1) == Decimal("22.00")


def test_old_name_gone_everywhere():
    assert not hasattr(shopkit, "calc_total")
    root = pathlib.Path(".")
    offenders = [
        str(p) for p in root.rglob("*")
        if p.is_file() and p.suffix in {".py", ".md"} and "_acceptance" not in p.parts
        and "calc_total" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == []


def test_behavior_preserved():
    c = Cart(tax_rate=0.05)
    c.add("pen", 1.5, 4)
    assert c.total() == Decimal("6.30")
    assert checkout(c, coupon_percent=10) == Decimal("5.67")
    assert daily_report([[{"price": 1}], [{"price": 2, "qty": 3}]]) == (2, Decimal("7.00"))
