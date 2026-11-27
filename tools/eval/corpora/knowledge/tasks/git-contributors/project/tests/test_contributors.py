from pathlib import Path

from gitrepo import Repo, contributors


def test_counts_authors(tmp_path: Path):
    repo = Repo(tmp_path)
    repo.commit("Ann <ann@example.com>", "one")
    repo.commit("Ben <ben@example.com>", "two")
    repo.commit("Ann <ann@example.com>", "three")
    assert contributors(tmp_path) == ["2\tAnn <ann@example.com>", "1\tBen <ben@example.com>"]


def test_counts_co_authors(tmp_path: Path):
    repo = Repo(tmp_path)
    repo.commit("Ann <ann@example.com>", "one\n\nCo-authored-by: Cid <cid@example.com>")
    assert contributors(tmp_path) == ["1\tAnn <ann@example.com>", "1\tCid <cid@example.com>"]
