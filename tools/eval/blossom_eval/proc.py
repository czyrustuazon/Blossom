"""Run a shell command with a timeout that really ends it.

`subprocess.run(..., shell=True, timeout=N)` kills only the shell when the timeout fires. On
Windows `npm test` -> cmd -> node keeps running and keeps the output pipes open, so the call
then waits for them forever: on 2026-11-21 one hung `node --test` stalled an A/B run for 83
minutes after its 120 s timeout. Here the whole process tree is killed first, and the wait
for the pipes is bounded.
"""
from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

PIPE_GRACE_SEC = 5


@dataclass
class ShellResult:
    returncode: int | None  # None when the command timed out
    stdout: str
    stderr: str
    timed_out: bool = False


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill `proc` and everything it started. The tree is walked before the shell dies."""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run_shell(command: str, *, cwd: str | Path, timeout: float,
              env: Mapping[str, str] | None = None) -> ShellResult:
    """Run `command` in a shell; on timeout kill its whole tree and return what it printed."""
    proc = subprocess.Popen(
        command, shell=True, cwd=str(cwd), env=dict(env) if env is not None else None,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        start_new_session=(os.name != "nt"),
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        return ShellResult(proc.returncode, out or "", err or "")
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=PIPE_GRACE_SEC)
        except subprocess.TimeoutExpired:
            # Something outside the tree still holds the pipes: stop waiting for it.
            out, err = "", ""
            for pipe in (proc.stdout, proc.stderr):
                try:
                    if pipe:
                        pipe.close()
                except OSError:
                    pass
        return ShellResult(None, out or "", err or "", timed_out=True)
