from decimal import Decimal


def make_entry(description, amount, category="misc"):
    if not description:
        raise ValueError("description is required")
    return {"description": description, "amount": Decimal(str(amount)), "category": category}
