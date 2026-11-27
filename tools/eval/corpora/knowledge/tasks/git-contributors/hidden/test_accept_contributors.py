"""Hidden acceptance for git-contributors: mailmap for authors and co-authors, trailers only from the
trailer block, case-insensitive emails, once per commit, merges skipped, ranges, run from a subdirectory."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # the workspace; this folder is copied in as _acceptance/
sys.path.insert(0, str(HERE))
from gitrepo import Repo, contributors  # noqa: E402

FULL = [
    "3\tAlice A. <alice@corp.com>",
    "2\tBob Builder <bob@new.org>",
    "2\tCarol <carol@x.io>",
    "2\tDave <dave@x.io>",
    "1\tErin <erin@x.io>",
]


def _history(tmp: Path) -> tuple[Repo, str]:
    repo = Repo(tmp)
    (tmp / ".mailmap").write_text("Alice A. <alice@corp.com>\nBob Builder <bob@new.org> <bob@old.org>\n",
                                  encoding="utf-8")
    repo.commit("Alice <alice@corp.com>", "init")
    repo.commit("bob <Bob@Old.org>",
                "feat: parser\n\nWe follow the Co-authored-by: Mallory <mallory@x.io> convention from now on.\n\n"
                "Co-authored-by: Alice <ALICE@corp.com>")
    third = repo.commit("Carol <carol@x.io>",
                        "fix: crash\n\nCo-authored-by: Robert Smith <bob@old.org>\nCo-authored-by: Dave <DAVE@x.io>")
    repo.git("checkout", "-q", "-b", "side")
    repo.commit("Dave <dave@x.io>", "side work", file="side.txt")
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "-m", "Merge branch 'side'\n\nCo-authored-by: Zed <zed@x.io>", "side",
             author="Alice <alice@corp.com>")
    repo.commit("Alice <alice@corp.com>", "docs\n\nCo-authored-by: Alice <alice@corp.com>")
    repo.commit("Carol <carol@x.io>", "chore: tidy\n\nco-authored-by: Erin <erin@x.io>", file="src/a.txt")
    return repo, third


def test_full_history(tmp_path: Path):
    _history(tmp_path)
    assert contributors(tmp_path) == FULL


def test_from_subdirectory(tmp_path: Path):
    _history(tmp_path)
    assert contributors(tmp_path / "src") == FULL


def test_range(tmp_path: Path):
    _, third = _history(tmp_path)
    assert contributors(tmp_path, f"{third}..HEAD") == [
        "1\tAlice A. <alice@corp.com>",
        "1\tCarol <carol@x.io>",
        "1\tDave <dave@x.io>",
        "1\tErin <erin@x.io>",
    ]
