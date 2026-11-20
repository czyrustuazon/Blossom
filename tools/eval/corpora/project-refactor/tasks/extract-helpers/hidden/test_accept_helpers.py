import ast
import pathlib

import pytest

from blogtool import textutil
from blogtool.archive import posts_between
from blogtool.authors import Author
from blogtool.posts import Post
from blogtool.tags import tag_index

PKG = pathlib.Path("blogtool")


def _defs(name_options):
    hits = []
    for path in PKG.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in name_options:
                hits.append(path.name)
    return hits


def test_each_helper_defined_once_in_textutil():
    assert _defs({"_slugify", "slugify"}) == ["textutil.py"]
    assert _defs({"_parse_date", "parse_date"}) == ["textutil.py"]


def test_helpers_behave():
    slug = getattr(textutil, "slugify", None) or textutil._slugify
    parse = getattr(textutil, "parse_date", None) or textutil._parse_date
    assert slug(" Héllo -- World!! ") == "hllo-world"
    assert parse("31/12/2020").isoformat() == "2020-12-31"
    with pytest.raises(ValueError):
        parse("2020.12.31")


def test_behavior_preserved():
    p1, p2 = Post("A", "2024-01-01"), Post("B b", "2024-02-01")
    assert p2.url() == "/2024/02/b-b/"
    assert Author("Ada  Lovelace", "10/12/1999").handle == "ada-lovelace"
    assert tag_index([(p1, ["Py Thon"]), (p2, ["py-thon"])]) == {"py-thon": ["a", "b-b"]}
    assert posts_between([p1, p2], "2024-01-15", "01/03/2024") == [p2]
