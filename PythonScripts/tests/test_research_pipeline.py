"""Unit tests for ResearchPipeline gate, planner parse, and gated search."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ResearchPipeline import (  # noqa: E402
    classify_research_need,
    parse_planner_queries,
    run_research_pipeline,
)


def test_classify_skip_tiny_edit():
    prompt = (
        "[EDITOR CONTEXT]\n"
        "<<<FILE path=\"app.py\">>>\nprint(1)\n<<<END_FILE>>>\n"
        "[USER REQUEST]\nfix the typo in app.py please"
    )
    assert classify_research_need(prompt, coding=True) == "skip"


def test_classify_skip_editor_without_search_keywords():
    prompt = (
        "[EDITOR CONTEXT]\n"
        "<<<FILE path=\"index.html\">>>\n<html></html>\n<<<END_FILE>>>\n"
        "[USER REQUEST]\nrefactor the header styles"
    )
    assert classify_research_need(prompt, coding=True) == "skip"


def test_classify_deep_on_research_language():
    assert (
        classify_research_need(
            "Please research the latest FastAPI lifespan docs and cite sources",
            coding=True,
        )
        == "deep"
    )


def test_classify_deep_on_version_uncertainty():
    assert (
        classify_research_need(
            "What is the latest version of pydantic v2 and breaking changes?",
            coding=True,
        )
        == "deep"
    )


def test_classify_simple_when_should_search(monkeypatch):
    monkeypatch.setattr(
        "ResearchPipeline.should_search",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr("ResearchPipeline.RESEARCH_DEEP_ENABLED", True)
    assert (
        classify_research_need("how do I open a file in python?", coding=True)
        == "simple"
    )


def test_parse_planner_queries_json_object():
    raw = 'Sure.\n{"queries": ["fastapi lifespan", "fastapi on_event migration"]}\n'
    assert parse_planner_queries(raw, max_queries=4) == [
        "fastapi lifespan",
        "fastapi on_event migration",
    ]


def test_parse_planner_queries_json_array():
    raw = '["alpha docs", "beta vs gamma"]'
    assert parse_planner_queries(raw, max_queries=2) == ["alpha docs", "beta vs gamma"]


def test_parse_planner_queries_line_fallback():
    raw = "- chromadb persistence\n- chromadb client settings\n"
    got = parse_planner_queries(raw, max_queries=4)
    assert "chromadb persistence" in got
    assert "chromadb client settings" in got


@patch("ResearchPipeline.learn_web_findings", return_value=["id1"])
@patch("ResearchPipeline.query_memories", return_value=[])
@patch("ResearchPipeline.web_search")
def test_pipeline_deep_mocked_search(mock_search, _mock_mem, mock_learn):
    mock_search.return_value = [
        {
            "title": "FastAPI Lifespan",
            "url": "https://example.com/lifespan",
            "snippet": "Use lifespan context managers instead of on_event.",
        }
    ]

    def complete(messages, temperature):
        return '{"queries": ["fastapi lifespan docs", "fastapi on_event deprecated"]}'

    result = run_research_pipeline(
        "Research the latest FastAPI lifespan docs and cite sources",
        coding=True,
        complete_fn=complete,
        force_mode="deep",
    )
    assert result.mode == "deep"
    assert mock_search.call_count >= 1
    assert mock_learn.call_count == 1
    assert "example.com/lifespan" in result.brief or "Lifespan" in result.brief
    assert len(result.sources) >= 1


@patch("ResearchPipeline.learn_web_findings", return_value=["id1"])
@patch("ResearchPipeline.query_memories", return_value=[])
@patch("ResearchPipeline.web_search")
def test_pipeline_simple_one_query(mock_search, _mock_mem, mock_learn):
    mock_search.return_value = [
        {
            "title": "Python open",
            "url": "https://docs.python.org/3/library/functions.html#open",
            "snippet": "Open file and return a corresponding file object.",
        }
    ]
    result = run_research_pipeline(
        "look up how open() works in python",
        coding=False,
        force_mode="simple",
    )
    assert result.mode == "simple"
    assert mock_search.call_count == 1
    assert mock_learn.call_count == 1
    assert "WEB SEARCH RESULTS" in result.brief


@patch("ResearchPipeline.learn_web_findings")
@patch("ResearchPipeline.query_memories", return_value=[])
@patch("ResearchPipeline.web_search")
def test_pipeline_disabled_deep_falls_back_to_simple(
    mock_search, _mock_mem, mock_learn, monkeypatch
):
    monkeypatch.setattr("ResearchPipeline.RESEARCH_PIPELINE_ENABLED", False)
    monkeypatch.setattr("ResearchPipeline.should_search", lambda *_a, **_k: True)
    mock_search.return_value = [
        {
            "title": "Docs",
            "url": "https://example.com/x",
            "snippet": "Useful snippet about the API that is long enough.",
        }
    ]
    mock_learn.return_value = ["id1"]
    result = run_research_pipeline(
        "Research the latest FastAPI lifespan docs",
        coding=True,
        force_mode="deep",
    )
    assert result.mode == "simple"
    assert mock_search.call_count == 1


def test_pipeline_skip_no_search():
    with (
        patch("ResearchPipeline.query_memories", return_value=[]),
        patch("ResearchPipeline.web_search") as mock_search,
    ):
        result = run_research_pipeline("hi", coding=False, force_mode="skip")
        assert result.mode == "skip"
        assert result.brief == ""
        mock_search.assert_not_called()
