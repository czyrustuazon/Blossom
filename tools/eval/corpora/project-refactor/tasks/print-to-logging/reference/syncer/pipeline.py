import logging

from .fetch import fetch
from .store import Store
from .transform import to_cents

logger = logging.getLogger(__name__)


def run_sync(source, store=None):
    store = store or Store()
    logger.info(f"sync start: {source}")
    rows = to_cents(fetch(source))
    saved = store.save(rows)
    logger.info(f"sync done: {source}")
    return saved, store
