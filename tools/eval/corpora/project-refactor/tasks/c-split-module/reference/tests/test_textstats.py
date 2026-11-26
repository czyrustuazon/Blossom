"""Builds src/*.c with the test driver (gcc, warnings as errors) and checks its output."""
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_and_run(tmp_path):
    gcc = shutil.which("gcc")
    assert gcc, "gcc not found on PATH"
    exe = tmp_path / "driver.exe"
    # Relative, forward-slash paths from the project root: msys gcc cannot resolve
    # #include "x.h" next to a source given as a Windows absolute path.
    sources = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "src").glob("*.c")) + ["tests/driver.c"]
    build = subprocess.run(
        [gcc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Isrc", "-o", exe.as_posix(), *sources],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return run.stdout.splitlines()


def test_wordcount(tmp_path):
    out = build_and_run(tmp_path)
    assert "lines 2 words 9 mean 4" in out
    assert "trimmed [the quick brown fox]" in out
    assert "heading [CHAPTER ONE]" in out


def test_grades(tmp_path):
    out = build_and_run(tmp_path)
    assert "mean 69 median 88 clamped 100 0" in out


def test_helpers(tmp_path):
    out = build_and_run(tmp_path)
    assert "empty 0 0" in out
    assert "clamp 0 5 9" in out
    assert "count 3 upper [ONE TWO  THREE]" in out
