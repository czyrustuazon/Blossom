"""Tests for agent_utils and routing."""

from __future__ import annotations

import pandas as pd
import pytest

from agent_utils.excel_ops import create_styled_excel
from agent_utils.io_ops import read_json, write_json
from agent_utils.data_ops import read_csv_summary
from agent_utils.pdf_ops import merge_pdfs
from AgentRouter import classify_route, is_agent_execution_request


def test_is_agent_execution_request_detects_pandas():
    assert is_agent_execution_request("Analyze this CSV with pandas and plot trends")


def test_is_agent_execution_request_skips_ide_tools():
    assert not is_agent_execution_request("```tool_call\n{\"name\":\"read_file\"}\n```")
    assert not is_agent_execution_request("[EDITOR CONTEXT]\npath=index.html")


def test_classify_route_prefers_agent_over_coding():
    def coding(_: str) -> bool:
        return True

    def japanese(_: str) -> bool:
        return False

    route = classify_route(
        "merge these pdfs into one file",
        is_coding_fn=coding,
        is_japanese_fn=japanese,
    )
    assert route == "agent"


def test_create_styled_excel(tmp_path):
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    out = create_styled_excel(df, str(tmp_path / "out.xlsx"))
    assert out.endswith("out.xlsx")
    assert (tmp_path / "out.xlsx").is_file()


def test_merge_pdfs_requires_inputs():
    with pytest.raises(ValueError):
        merge_pdfs([], "out.pdf")


def test_read_csv_summary(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("a,b\n1,x\n2,y\n", encoding="utf-8")
    summary = read_csv_summary(str(csv_path))
    assert "2 rows x 2 cols" in summary
    assert "head(5)" in summary


def test_read_write_json(tmp_path):
    path = tmp_path / "data.json"
    write_json(str(path), {"ok": True, "n": 3})
    assert read_json(str(path)) == {"ok": True, "n": 3}
