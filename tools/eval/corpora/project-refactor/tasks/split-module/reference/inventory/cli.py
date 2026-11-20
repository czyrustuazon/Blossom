import argparse

from .models import Item
from .reports import format_report
from .storage import Store


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
