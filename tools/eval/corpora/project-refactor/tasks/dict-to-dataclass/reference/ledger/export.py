def to_rows(entries):
    rows = [["description", "amount", "category"]]
    for entry in entries:
        rows.append([entry.description, f"{entry.amount:.2f}", entry.category])
    return rows
