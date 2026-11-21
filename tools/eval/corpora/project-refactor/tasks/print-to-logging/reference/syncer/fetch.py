import logging

logger = logging.getLogger(__name__)

SOURCES = {
    "orders": [
        {"id": 1, "amount": "10.50"},
        {"id": 2, "amount": "oops"},
        {"id": 3, "amount": "4.25"},
    ],
    "empty": [],
}


def fetch(source):
    logger.info(f"fetching {source}")
    if source not in SOURCES:
        logger.error(f"unknown source {source}")
        raise KeyError(source)
    rows = SOURCES[source]
    if not rows:
        logger.warning(f"source {source} is empty")
    return list(rows)
