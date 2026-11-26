# netclient

A tiny client that fetches URLs through a pluggable transport, retries 5xx responses and
connection errors with exponential backoff, and caches successful responses.

- `netclient/config.py`: shared settings
- `netclient/client.py`: `Client.fetch`
- `netclient/cache.py`: `ResponseCache`

Run the tests with `python -m pytest -q tests`.
