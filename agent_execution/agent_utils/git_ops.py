"""Git helpers — stage, diff, commit, push."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _run_git(args: list[str], repo_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=False,
    )


def git_get_staged_diff(repo_path: str = ".") -> str:
    """Stage all pending changes and return the staged git diff as text."""
    root = Path(repo_path).resolve()
    if not (root / ".git").exists():
        raise FileNotFoundError(f"Not a git repository: {root}")

    add = _run_git(["add", "-A"], root)
    if add.returncode != 0:
        raise RuntimeError(add.stderr.strip() or "git add failed")

    diff = _run_git(["diff", "--cached"], root)
    if diff.returncode != 0:
        raise RuntimeError(diff.stderr.strip() or "git diff --cached failed")
    return diff.stdout


def git_auto_commit_and_push(
    commit_msg: str,
    repo_path: str = ".",
    branch: str | None = None,
    remote: str = "origin",
) -> dict[str, Any]:
    """Stage all changes, commit, and push to the remote branch."""
    root = Path(repo_path).resolve()
    if not (root / ".git").exists():
        raise FileNotFoundError(f"Not a git repository: {root}")

    msg = (commit_msg or "").strip()
    if not msg:
        raise ValueError("commit_msg must not be empty")

    add = _run_git(["add", "-A"], root)
    if add.returncode != 0:
        raise RuntimeError(add.stderr.strip() or "git add failed")

    status = _run_git(["status", "--porcelain"], root)
    if not status.stdout.strip():
        return {
            "ok": True,
            "committed": False,
            "pushed": False,
            "message": "Nothing to commit",
            "repo_path": str(root),
        }

    commit = _run_git(["commit", "-m", msg], root)
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr.strip() or "git commit failed")

    if branch is None:
        branch_proc = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
        if branch_proc.returncode != 0:
            raise RuntimeError(branch_proc.stderr.strip() or "could not resolve branch")
        branch = branch_proc.stdout.strip()

    push = _run_git(["push", remote, branch], root)
    if push.returncode != 0:
        raise RuntimeError(push.stderr.strip() or "git push failed")

    return {
        "ok": True,
        "committed": True,
        "pushed": True,
        "branch": branch,
        "remote": remote,
        "repo_path": str(root),
        "stdout": (commit.stdout + push.stdout).strip(),
    }


def git_status_short(repo_path: str = ".") -> str:
    """Compact git status (branch + porcelain lines, no full diff)."""
    root = Path(repo_path).resolve()
    if not (root / ".git").exists():
        raise FileNotFoundError(f"Not a git repository: {root}")

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    status = _run_git(["status", "--porcelain", "-b"], root)
    if branch.returncode != 0:
        raise RuntimeError(branch.stderr.strip() or "could not resolve branch")
    if status.returncode != 0:
        raise RuntimeError(status.stderr.strip() or "git status failed")

    lines = [f"branch: {branch.stdout.strip()}", status.stdout.strip() or "(clean)"]
    return "\n".join(lines)
