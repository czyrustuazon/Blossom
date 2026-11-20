"""Inventory tracker: models, JSON storage, reports and CLI all in one file."""
import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


# ---------------------------------------------------------------- models
@dataclass
class Item:
    sku: str
    name: str
    qty: int = 0
    unit_cost: float = 0.0
    tags: list = field(default_factory=list)

    @property
    def value(self) -> float:
        return round(self.qty * self.unit_cost, 2)

    def needs_restock(self, threshold: int = 5) -> bool:
        return self.qty < threshold


# --------------------------------------------------------------- storage
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


# --------------------------------------------------------------- reports
def format_report(items, threshold: int = 5) -> str:
    lines = [f"{'SKU':<8}{'NAME':<16}{'QTY':>5}{'VALUE':>10}"]
    total = 0.0
    for item in sorted(items, key=lambda i: i.sku):
        flag = " !" if item.needs_restock(threshold) else ""
        lines.append(f"{item.sku:<8}{item.name:<16}{item.qty:>5}{item.value:>10.2f}{flag}")
        total += item.value
    lines.append(f"{'TOTAL':<29}{total:>10.2f}")
    return "\n".join(lines)


def restock_list(items, threshold: int = 5):
    return [i.sku for i in sorted(items, key=lambda i: i.sku) if i.needs_restock(threshold)]


# ------------------------------------------------------------------- cli
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="inventory")
    parser.add_argument("--db", default="inventory.json")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("sku")
    add.add_argument("name")
    add.add_argument("--qty", type=int, default=0)
    add.add_argument("--cost", type=float, default=0.0)
    adj = sub.add_parser("adjust")
    adj.add_argument("sku")
    adj.add_argument("delta", type=int)
    sub.add_parser("report")
    args = parser.parse_args(argv)

    store = Store(args.db)
    if args.cmd == "add":
        store.add(Item(args.sku, args.name, args.qty, args.cost))
    elif args.cmd == "adjust":
        store.adjust(args.sku, args.delta)
    elif args.cmd == "report":
        print(format_report(store.items.values()))
        return 0
    store.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
