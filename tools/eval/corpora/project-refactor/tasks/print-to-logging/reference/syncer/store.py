import logging

logger = logging.getLogger(__name__)


class Store:
    def __init__(self):
        self.rows = {}

    def save(self, rows):
        for row in rows:
            if row["id"] in self.rows:
                logger.warning(f"overwriting row {row['id']}")
            self.rows[row["id"]] = row["cents"]
        logger.info(f"saved {len(rows)} rows")
        return len(rows)
