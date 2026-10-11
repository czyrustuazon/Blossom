"""CSV / tabular quick summaries for the agent layer."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_csv_summary(
    path: str,
    *,
    nrows: int = 5,
    max_cols: int = 20,
) -> str:
    """Load a CSV and return a compact text summary (shape, dtypes, head, describe)."""
    src = Path(path).resolve()
    if not src.is_file():
        raise FileNotFoundError(src)

    df = pd.read_csv(src)
    if df.shape[1] > max_cols:
        df = df.iloc[:, :max_cols]
        col_note = f" (showing first {max_cols} columns)"
    else:
        col_note = ""

    lines = [
        f"path: {src}",
        f"shape: {df.shape[0]} rows x {df.shape[1]} cols{col_note}",
        f"columns: {', '.join(str(c) for c in df.columns)}",
        f"dtypes:\n{df.dtypes.to_string()}",
        f"head({nrows}):\n{df.head(nrows).to_string()}",
    ]
    numeric = df.select_dtypes(include="number")
    if not numeric.empty:
        lines.append(f"describe:\n{numeric.describe().to_string()}")
    return "\n\n".join(lines)
