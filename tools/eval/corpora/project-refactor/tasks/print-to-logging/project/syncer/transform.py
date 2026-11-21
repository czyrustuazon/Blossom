def to_cents(rows):
    out = []
    for row in rows:
        try:
            cents = round(float(row["amount"]) * 100)
        except ValueError:
            print(f"WARNING: skipping row {row['id']}: bad amount {row['amount']!r}")
            continue
        out.append({"id": row["id"], "cents": cents})
    print(f"transformed {len(out)} of {len(rows)} rows")
    return out
