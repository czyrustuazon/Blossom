"""Matplotlib figure export."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def save_figure(fig: Any, output_path: str, *, dpi: int = 120) -> str:
    """Save a matplotlib figure to disk and return the path."""
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    return str(out)
