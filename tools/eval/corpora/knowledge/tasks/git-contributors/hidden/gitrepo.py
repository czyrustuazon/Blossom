"""Builds throwaway git repositories and runs tools/contributors.sh in them."""
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "contributors.sh"


def bash() -> str:
    for cand in (r"C:\devkitPro\msys2\usr\bin\bash.exe", r"C:\Program Files\Git\bin\bash.exe"):
        if Path(cand).is_file():
            return cand
    found = shutil.which("bash")
    assert found, "bash not found"
    return found


class Repo:
    def __init__(self, path: Path):
        self.path = path
        self.n = 0
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str, author: str = "Ci <ci@example.com>") -> str:
        name, email = author[:-1].split(" <")
        self.n += 1
        date = f"2026-01-01T00:{self.n // 60:02d}:{self.n % 60:02d}+00:00"
        env = dict(os.environ, GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_NAME="Ci",
                   GIT_COMMITTER_EMAIL="ci@example.com", GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date,
                   GIT_CONFIG_NOSYSTEM="1", HOME=str(self.path))
        p = subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=self.path, env=env,
                           capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        return p.stdout.strip()

    def commit(self, author: str, message: str, file: str = "log.txt"):
        f = self.path / file
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fh:
            fh.write(message.splitlines()[0] + "\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message, author=author)
        return self.git("rev-parse", "HEAD")


def contributors(cwd: Path, *args: str) -> list[str]:
    p = subprocess.run([bash(), SCRIPT.as_posix(), *args], cwd=cwd, capture_output=True, text=True,
                       env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1"))
    assert p.returncode == 0, p.stderr
    return [line.rstrip("\r") for line in p.stdout.splitlines() if line.strip()]
