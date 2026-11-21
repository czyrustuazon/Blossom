SOURCES = {
    "orders": [
        {"id": 1, "amount": "10.50"},
        {"id": 2, "amount": "oops"},
        {"id": 3, "amount": "4.25"},
    ],
    "empty": [],
}


def fetch(source):
    print(f"fetching {source}")
    if source not in SOURCES:
        print(f"ERROR: unknown source {source}")
        raise KeyError(source)
    rows = SOURCES[source]
    if not rows:
        print(f"WARNING: source {source} is empty")
    return list(rows)
