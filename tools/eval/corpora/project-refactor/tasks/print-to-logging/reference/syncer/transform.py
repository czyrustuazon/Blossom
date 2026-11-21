import logging

logger = logging.getLogger(__name__)


def to_cents(rows):
    out = []
    for row in rows:
        try:
            cents = round(float(row["amount"]) * 100)
        except ValueError:
            logger.warning(f"skipping row {row['id']}: bad amount {row['amount']!r}")
            continue
        out.append({"id": row["id"], "cents": cents})
    logger.info(f"transformed {len(out)} of {len(rows)} rows")
    return out
