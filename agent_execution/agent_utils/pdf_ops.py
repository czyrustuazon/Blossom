"""PDF text/table extraction and merge helpers."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd
import pdfplumber
from pypdf import PdfWriter


def extract_pdf_text(pdf_path: str, max_pages: int = 10) -> str:
    """Extract plain text from a PDF up to max_pages."""
    path = Path(pdf_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[: max(1, max_pages)]:
            chunks.append(page.extract_text() or "")
    return "\n\n".join(chunks).strip()


def extract_pdf_tables(pdf_path: str) -> List[pd.DataFrame]:
    """Extract tables from a PDF into pandas DataFrames."""
    path = Path(pdf_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    frames: list[pd.DataFrame] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table or len(table) < 2:
                    continue
                header = [str(c or "").strip() for c in table[0]]
                rows = [
                    [str(c or "").strip() for c in row]
                    for row in table[1:]
                    if any(row)
                ]
                if rows:
                    frames.append(pd.DataFrame(rows, columns=header))
    return frames


def merge_pdfs(input_paths: List[str], output_path: str) -> str:
    """Merge multiple PDF files into a single output PDF."""
    if not input_paths:
        raise ValueError("input_paths must not be empty")

    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    writer = PdfWriter()
    for raw in input_paths:
        src = Path(raw).resolve()
        if not src.is_file():
            raise FileNotFoundError(src)
        writer.append(str(src))
    with out.open("wb") as fh:
        writer.write(fh)
    writer.close()
    return str(out)
