"""A tiny HTTP-ish client with retries and a response cache."""

from .cache import ResponseCache
from .client import Client, FetchError

__all__ = ["Client", "FetchError", "ResponseCache"]
