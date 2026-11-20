from .pricing import compute_order_total


class Cart:
    def __init__(self, tax_rate=0.0):
        self.tax_rate = tax_rate
        self.items = []

    def add(self, name, price, qty=1):
        self.items.append({"name": name, "price": price, "qty": qty})

    def total(self):
        return compute_order_total(self.items, self.tax_rate)
