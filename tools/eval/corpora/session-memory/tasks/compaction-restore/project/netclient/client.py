"""Fetch URLs through a pluggable transport, with retries and caching."""

import time

from . import config
from .cache import ResponseCache


class FetchError(Exception):
    """A URL could not be fetched."""


class Client:
    def __init__(self, transport, cache=None, sleep=time.sleep):
        # transport(url, headers) -> (status, body); may raise OSError.
        self.transport = transport
        self.cache = cache if cache is not None else ResponseCache()
        self.sleep = sleep

    def headers(self):
        return {"User-Agent": config.USER_AGENT, "Accept": "application/json"}

    def fetch(self, url):
        cached = self.cache.get(url)
        if cached is not None:
            return cached
        last_error = None
        for attempt in range(config.MAX_RETRIES):
            try:
                status, body = self.transport(url, self.headers())
            except OSError as exc:
                last_error = exc
            else:
                if status == 200:
                    self.cache.put(url, body)
                    return body
                if 400 <= status < 500:
                    raise FetchError(f"{url}: HTTP {status}")
                last_error = FetchError(f"{url}: HTTP {status}")
            if attempt + 1 < config.MAX_RETRIES:
                self.sleep(config.BACKOFF_SECONDS * (2 ** attempt))
        raise FetchError(f"{url}: gave up after {config.MAX_RETRIES} attempts") from last_error
