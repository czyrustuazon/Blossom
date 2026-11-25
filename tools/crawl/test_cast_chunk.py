"""cAST chunker: size budget, no lost code, scope stamps, fallbacks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cast_chunk import (  # noqa: E402
    DEFAULT_BUDGET,
    cast_split,
    chunk_text,
    doc_split,
    grammar_for,
    nws_len,
    stamp,
    strip_crawl_header,
)

pytest.importorskip("tree_sitter_language_pack")

PY = "\n\n".join(
    f'''class Store{i}:
    """Store number {i}."""

    def __init__(self):
        self.data = {{}}
        self.hits = 0

    def get(self, key, default=None):
        self.hits += 1
        if key in self.data:
            return self.data[key]
        return default

    def put(self, key, value):
        if key is None:
            raise ValueError("key is required for store {i}")
        self.data[key] = value
        return value
'''
    for i in range(6)
)


def test_small_code_stays_one_part():
    parts = cast_split("def f():\n    return 1\n", "python")
    assert len(parts) == 1


def test_parts_fit_the_budget_and_lose_no_code():
    parts = cast_split(PY, "python", budget=200)
    assert len(parts) > 3
    assert all(nws_len(p.text) <= 200 for p in parts)
    # Every non-whitespace character is kept, in order, exactly once.
    assert "".join(p.text for p in parts).replace(" ", "").replace("\n", "") == PY.replace(" ", "").replace("\n", "")


def test_split_parts_carry_their_class_scope():
    parts = cast_split(PY, "python", budget=120)
    scoped = [p for p in parts if p.scope]
    assert scoped and all(p.scope[0].startswith("Store") for p in scoped)
    assert "in Store" in stamp(scoped[0], where="acme/store.py", language="python")


def test_c_and_engine_languages_parse():
    c = "struct point { int x; int y; };\n" + "\n".join(
        f"int add{i}(int a, int b) {{ int s = a + b; if (s > {i}) {{ return s - {i}; }} return s; }}" for i in range(40)
    )
    parts, method = chunk_text(c, language="c", path="src/math.c")
    assert method == "cast" and len(parts) > 1
    gd = "extends Node2D\n\n" + "\n\n".join(f"func step_{i}(delta):\n\tposition.x += {i} * delta\n\treturn position" for i in range(60))
    parts, method = chunk_text(gd, language="gdscript", path="player.gd")
    assert method == "cast" and all(nws_len(p.text) <= DEFAULT_BUDGET for p in parts)


def test_unknown_language_falls_back_to_blank_line_blocks():
    text = "\n\n".join("line " * 40 for _ in range(10))
    parts, method = chunk_text(text, language="cobol", path="x.cbl")
    assert method == "lines" and len(parts) > 1


def test_markdown_splits_at_headings_and_keeps_the_heading_path():
    md = "# Guide\n\nIntro.\n\n## Install\n\n" + ("pip install thing. " * 60) + "\n\n## Use\n\n" + ("call it. " * 80)
    parts = doc_split(md, budget=200)
    assert len(parts) >= 3
    assert any(p.scope == ["Guide", "Install"] for p in parts)
    assert any(p.scope == ["Guide", "Use"] for p in parts)


def test_crawler_header_is_stripped_before_parsing():
    row = "# acme/x — a.py\n# language: python\n# url: https://github.com/acme/x\n\n# real comment\nx = 1\n"
    assert strip_crawl_header(row) == "# real comment\nx = 1\n"
    assert strip_crawl_header("# just a comment\n\nx = 1") == "# just a comment\n\nx = 1"


def test_grammar_lookup():
    assert grammar_for("csharp") == "csharp"
    assert grammar_for(None, "Makefile") == "make"
    assert grammar_for("", "shaders/water.frag") == "glsl"
    assert grammar_for("cobol", "x.cbl") is None
