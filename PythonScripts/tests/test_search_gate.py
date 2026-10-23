"""Need-based web search gate."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from SearchGate import assess_search_need  # noqa: E402


@pytest.mark.parametrize(
    "prompt",
    [
        "Write a python function add(a, b) with type hints. Code only.",
        "refactor this class to use dataclasses",
        "explain the difference between a list vs tuple in python",
        "how do I reverse a linked list?",
        "fix the off-by-one error in my loop",
        "write a function that returns today's date",
        "build an online store page in html",
    ],
)
def test_self_contained_coding_skips(prompt):
    assert not assess_search_need(prompt, coding=True).search


@pytest.mark.parametrize(
    "prompt",
    [
        "look up how asyncio.TaskGroup handles cancellation",
        "what is the latest version of pydantic?",
        "is distutils deprecated in python 3.12?",
        "check the docs for the fastapi lifespan api",
        "getting TS2345 from @tanstack/react-query@5.8 useQuery types",
        "discord.py v2 slash command sync returns 403",
        "what changed in the stripe api in 2026?",
    ],
)
def test_outside_knowledge_searches(prompt):
    assert assess_search_need(prompt, coding=True).search


def test_editor_dump_needs_explicit_signal():
    dump = (
        "[EDITOR CONTEXT]\n<<<FILE path=\"bot.py\">>>\nimport discord\n<<<END_FILE>>>\n"
        "[USER REQUEST]\n"
    )
    assert not assess_search_need(dump + "add a ping command using discord.py v2", coding=True).search
    assert assess_search_need(dump + "check the docs and add a ping command", coding=True).search


def test_casual_world_facts_search():
    assert assess_search_need("what's the weather forecast for Tokyo this week?").search
    assert not assess_search_need("how was your day?").search


def test_close_prior_memory_covers_non_volatile_need():
    prompt = "discord.py v2 slash command sync returns 403"
    near = [{"distance": 0.12}]
    far = [{"distance": 0.6}]
    assert not assess_search_need(prompt, coding=True, prior_hits=near).search
    assert assess_search_need(prompt, coding=True, prior_hits=far).search
    assert assess_search_need("latest pydantic release", coding=True, prior_hits=near).search
