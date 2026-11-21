"""A timed-out command must end, along with everything it started.

A/B run of 2026-11-21, cycle off3, callbacks-to-async: the coder's `npm test` hung, the
120 s timeout killed only the shell, and `node --test` kept the output pipe open — the loop
waited 83 minutes until the node processes were killed by hand.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from blossom_eval import agent_loop
from blossom_eval.proc import run_shell

# The shell starts python, which starts a second python that sleeps while holding the pipe.
HANG = (
    "import subprocess, sys\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
    "print(child.pid, flush=True)\n"
    "child.wait()\n"
)


def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _gone(pid: int, within: float = 5.0) -> bool:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


def test_timeout_kills_the_whole_tree_and_returns(tmp_path: Path):
    (tmp_path / "hang.py").write_text(HANG, encoding="utf-8")
    t0 = time.monotonic()
    result = run_shell(f'"{sys.executable}" hang.py', cwd=tmp_path, timeout=3)
    assert time.monotonic() - t0 < 30
    assert result.timed_out and result.returncode is None
    grandchild = int(result.stdout.strip())  # output printed before the timeout is kept
    assert _gone(grandchild)


def test_a_finished_command_reports_exit_code_and_output(tmp_path: Path):
    ok = run_shell(f'"{sys.executable}" -c "print(41 + 1)"', cwd=tmp_path, timeout=30)
    assert (ok.returncode, ok.stdout.strip(), ok.timed_out) == (0, "42", False)
    bad = run_shell(f'"{sys.executable}" -c "import sys; sys.exit(3)"', cwd=tmp_path, timeout=30)
    assert bad.returncode == 3 and not bad.timed_out


def test_run_command_tool_reports_the_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "hang.py").write_text(HANG, encoding="utf-8")
    monkeypatch.setattr(agent_loop, "COMMAND_TIMEOUT_SEC", 3)
    ok, result = agent_loop.Workspace(tmp_path).t_run_command({"command": "python hang.py"})
    assert ok is False
    assert result.startswith("Timed out after 3s: python hang.py")
    assert _gone(int(result.splitlines()[1]))
