from decimal import Decimal


class Book:
    def __init__(self):
        self.entries = []

    def add(self, entry):
        if entry["amount"] == 0:
            raise ValueError("amount must not be zero")
        self.entries.append(entry)
        return entry

    def balance(self):
        return sum((e["amount"] for e in self.entries), Decimal("0"))

    def find(self, text):
        return [e for e in self.entries if text.lower() in e["description"].lower()]

    def in_category(self, category):
        return [e for e in self.entries if e["category"] == category]
