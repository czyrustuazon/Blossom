"""Game logic on the host (gcc) and the full 3DS build (devkitARM)."""
import shutil
import subprocess
from pathlib import Path

from devkit import ROOT, build_3ds


def test_game_logic(tmp_path: Path):
    gcc = shutil.which("gcc")
    assert gcc, "gcc not found on PATH"
    exe = tmp_path / "game_driver.exe"
    b = subprocess.run([gcc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Isrc", "-o", exe.as_posix(),
                        "src/game.c", "tests/game_driver.c"], capture_output=True, text=True, cwd=ROOT)
    assert b.returncode == 0, b.stderr
    out = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30).stdout.split()
    assert out == ["serve", "197", "117", "clamp", "0", "200", "score", "0", "1", "bounce", "-3"]


def test_3ds_build(tmp_path: Path):
    build_3ds(tmp_path)
    assert (tmp_path / "game.elf").is_file()
