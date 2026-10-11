"""JSON helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: str) -> Any:
    """Read and parse a JSON file."""
    src = Path(path).resolve()
    if not src.is_file():
        raise FileNotFoundError(src)
    return json.loads(src.read_text(encoding="utf-8"))


def write_json(path: str, data: Any, *, indent: int = 2) -> str:
    """Write data to JSON and return the output path."""
    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(out)
