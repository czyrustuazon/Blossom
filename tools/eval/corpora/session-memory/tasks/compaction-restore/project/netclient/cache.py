"""In-memory response cache with a time-to-live."""

import time

from . import config


class ResponseCache:
    def __init__(self, ttl=config.CACHE_TTL_SECONDS, clock=time.monotonic):
        self.ttl = ttl
        self.clock = clock
        self._items = {}

    def get(self, key):
        item = self._items.get(key)
        if item is None:
            return None
        stored_at, value = item
        if self.clock() - stored_at > self.ttl:
            return None
        return value

    def put(self, key, value):
        self._items[key] = (self.clock(), value)

    def __len__(self):
        return len(self._items)
