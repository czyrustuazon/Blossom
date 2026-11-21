from decimal import Decimal


def by_category(entries):
    totals = {}
    for entry in entries:
        totals[entry["category"]] = totals.get(entry["category"], Decimal("0")) + entry["amount"]
    return dict(sorted(totals.items()))


def largest(entries, n=1):
    ranked = sorted(entries, key=lambda e: (-abs(e["amount"]), e["description"]))
    return ranked[:n]
