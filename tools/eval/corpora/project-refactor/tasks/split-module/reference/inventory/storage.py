import json
from dataclasses import asdict
from pathlib import Path

from .models import Item


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.items = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = {r["sku"]: Item(**r) for r in raw}

    def add(self, item: Item) -> None:
        if item.sku in self.items:
            raise KeyError(f"duplicate sku {item.sku}")
        self.items[item.sku] = item

    def adjust(self, sku: str, delta: int) -> Item:
        item = self.items[sku]
        if item.qty + delta < 0:
            raise ValueError("stock cannot go negative")
        item.qty += delta
        return item

    def save(self) -> None:
        data = [asdict(i) for i in sorted(self.items.values(), key=lambda i: i.sku)]
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
