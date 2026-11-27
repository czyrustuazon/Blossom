"""The app builds for the 3DS with devkitARM and the effects are in the romfs."""
from pathlib import Path

from devkit import ROOT, build_3ds


def test_3ds_build(tmp_path: Path):
    build_3ds(tmp_path)
    assert (tmp_path / "game.elf").is_file()


def test_effects_present():
    for name in ("bounce.pcm", "score.pcm"):
        data = (ROOT / "romfs" / "sfx" / name).read_bytes()
        assert data and len(data) % 2 == 0, name
