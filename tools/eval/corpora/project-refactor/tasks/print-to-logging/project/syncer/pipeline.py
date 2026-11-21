from .fetch import fetch
from .store import Store
from .transform import to_cents


def run_sync(source, store=None):
    store = store or Store()
    print(f"sync start: {source}")
    rows = to_cents(fetch(source))
    saved = store.save(rows)
    print(f"sync done: {source}")
    return saved, store
