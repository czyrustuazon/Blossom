"""Time ChatRouter /v1/blossom/summarize on a synthetic ~50k-token session.

Usage: python tools/bench_summarize.py <router_url> [max_chars]
"""

import json
import random
import sys
import time
import urllib.request

url = sys.argv[1].rstrip("/")
max_chars = int(sys.argv[2]) if len(sys.argv) > 2 else 24000

random.seed(2)
words = (
    "parser token buffer render module config cache index widget queue thread socket "
    "schema layout router handler fixed failed decided file path"
).split()
turns = [
    f"User: turn {i}: " + " ".join(random.choice(words) for _ in range(60))
    + f"\nAssistant: did step {i} in src/mod{i % 9}.ts: "
    + " ".join(random.choice(words) for _ in range(60))
    for i in range(220)
]
text = (
    "[PREVIOUS SUMMARY]\n" + "Earlier: user builds a parser. " * 300
    + "\n\n[NEW TURNS TO FOLD IN]\n" + "\n".join(turns)
)
started = time.time()
req = urllib.request.Request(
    f"{url}/v1/blossom/summarize",
    data=json.dumps({"text": text, "max_chars": max_chars}).encode(),
    headers={"Content-Type": "application/json"},
)
result = json.load(urllib.request.urlopen(req, timeout=1200))
print(
    f"input={len(text)} chars max_chars={max_chars} role={result['role']} "
    f"secs={time.time() - started:.1f} summary={len(result['summary'])} chars"
)
