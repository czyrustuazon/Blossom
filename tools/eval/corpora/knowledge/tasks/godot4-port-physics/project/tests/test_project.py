"""Static sanity checks of the Godot project (no Godot binary on the test machine)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scripts_extend_something():
    for gd in (ROOT / "scripts").glob("*.gd"):
        assert re.search(r"^extends\s+\w+", gd.read_text(encoding="utf-8"), re.M), gd.name


def test_scene_resources_exist():
    for scene in (ROOT / "scenes").glob("*.tscn"):
        text = scene.read_text(encoding="utf-8")
        assert text.startswith("[gd_scene"), scene.name
        for path in re.findall(r'path="res://([^"]+)"', text):
            assert (ROOT / path).is_file(), f"{scene.name} -> {path}"


def test_main_scene_set():
    text = (ROOT / "project.godot").read_text(encoding="utf-8")
    m = re.search(r'run/main_scene="res://([^"]+)"', text)
    assert m and (ROOT / m.group(1)).is_file()
