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


def test_inventory_numbers(tmp_path):
    out = build_and_run(tmp_path)
    assert "units 150" in out
    assert "value 1450" in out
    assert "empty 1" in out
    assert "washer 0" in out
    assert "washer_restocked 7" in out


def test_order_fulfillment(tmp_path):
    out = build_and_run(tmp_path)
    assert "short 13" in out
    assert "bolt_left 70" in out
    assert "nut_left 0" in out


def test_field_offset_lookup(tmp_path):
    out = build_and_run(tmp_path)
    assert "offset_ok 1" in out


def test_csv_report(tmp_path):
    out = build_and_run(tmp_path)
    start = next(i for i, line in enumerate(out) if line.startswith("name,"))
    assert out[start + 1:] == ["bolt,70,12", "nut,0,5", "washer,7,2"]
