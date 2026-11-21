class Store:
    def __init__(self):
        self.rows = {}

    def save(self, rows):
        for row in rows:
            if row["id"] in self.rows:
                print(f"WARNING: overwriting row {row['id']}")
            self.rows[row["id"]] = row["cents"]
        print(f"saved {len(rows)} rows")
        return len(rows)
