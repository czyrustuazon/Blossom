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
