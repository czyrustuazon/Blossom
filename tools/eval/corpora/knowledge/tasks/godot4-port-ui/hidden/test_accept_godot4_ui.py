"""Hidden acceptance for godot4-port-ui: HUD + settings scripts, the HUD scene and project.godot use
Godot 4 APIs and property names, keep their behaviour and values, and the script matches the scene."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # the workspace; this folder is copied in as _acceptance/
sys.path.insert(0, str(HERE))
from gdcheck import dollar_paths, gd, has, no, node_names, old_connect  # noqa: E402


def test_hud_annotations_and_setters():
    s = gd(ROOT, "scripts/hud.gd")
    has(r"^@tool\b", s, "hud.gd must be an @tool script")
    no(r"^\s*tool\b", s, "hud.gd: Godot 3 `tool` keyword")
    no(r"^\s*(export|onready)\b", s, "hud.gd: Godot 3 export/onready keyword")
    no(r"\bsetget\b", s, "hud.gd: setget")
    has(r"@export_range\(\s*0\s*,\s*10\s*\)\s*var\s+lives\b[^\n]*3", s, "lives stays a 0..10 range export of 3")
    for prop, setter in (("lives", "set_lives"), ("score", "set_score")):
        has(r"var\s+" + prop + r"\b[^\n]*:\s*(?:\n\s+)?set\s*(?:=\s*" + setter + r"\b|\()", s,
            f"{prop} still has a setter")
    no(r"\bPoolStringArray\b", s, "hud.gd: PoolStringArray")
    has(r"\bPackedStringArray\b", s, "history is a PackedStringArray")
    no(r"\bEngine\.editor_hint\b", s, "hud.gd: Engine.editor_hint")
    has(r"\bEngine\.is_editor_hint\(\)", s, "editor check uses Engine.is_editor_hint()")


def test_hud_signals_tween_await():
    s = gd(ROOT, "scripts/hud.gd")
    old_connect(s, "hud.gd")
    has(r"\.bind\(\s*i\s*\)|func\s*\(\s*\)\s*:\s*_on_difficulty_pressed\(\s*i\s*\)", s,
        "difficulty buttons pass their index (Callable.bind or a lambda)")
    no(r"\binterpolate_property\b|\$Tween\b|\bTween\.new\(", s, "hud.gd: Godot 3 Tween node API")
    has(r"\bcreate_tween\(\)", s, "score pop uses create_tween()")
    has(r"\btween_property\(\s*score_label\s*,\s*\"scale\"", s, "score pop tweens the label's scale")
    no(r"rect_scale", s, "hud.gd: rect_scale")
    has(r"TRANS_BACK", s, "score pop keeps TRANS_BACK")
    has(r"0\.25", s, "score pop keeps 0.25 s")
    no(r"\byield\s*\(", s, "hud.gd: yield")
    has(r"\bawait\s+get_tree\(\)\.create_timer\(\s*seconds\s*\)\.timeout\b", s, "show_message awaits the timer")
    no(r"\.empty\(\)", s, "hud.gd: .empty() (is_empty() in Godot 4)")
    has(r"start_pressed", s, "start_pressed still emitted")
    has(r"difficulty_chosen", s, "difficulty_chosen still emitted")


def test_settings_script():
    s = gd(ROOT, "scripts/settings.gd")
    no(r"\bFile\.new\(|\bFile\.(READ|WRITE)\b", s, "settings.gd: Godot 3 File class")
    has(r"\bFileAccess\.open\(", s, "settings use FileAccess.open")
    no(r"\bparse_json\b|\bto_json\b", s, "settings.gd: parse_json/to_json")
    has(r"\bJSON\.parse_string\(|\bJSON\.new\(\)", s, "settings parse JSON with the JSON class")
    has(r"\bJSON\.stringify\(", s, "settings save with JSON.stringify")
    no(r"\bstepify\b", s, "settings.gd: stepify")
    has(r"\bsnappedf?\([^\n]*0\.05\s*\)", s, "volume still snapped to 0.05")
    no(r"\bOS\.window_fullscreen\b", s, "settings.gd: OS.window_fullscreen")
    has(r"\bDisplayServer\.window_set_mode\(", s, "fullscreen via DisplayServer.window_set_mode")
    no(r"\blinear2db\b", s, "settings.gd: linear2db")
    has(r"\blinear_to_db\(", s, "volume via linear_to_db")
    has(r'"user://settings\.json"', s, "same settings path")


def test_hud_scene_properties():
    text = (ROOT / "scenes" / "HUD.tscn").read_text(encoding="utf-8")
    types = set(node_names(text).values())
    assert "Tween" not in types, "HUD.tscn still has a Tween node (removed in Godot 4)"
    no(r"^margin_(left|top|right|bottom)\s*=", text, "HUD.tscn: margin_* (offset_* in Godot 4)")
    no(r"^rect_(min_size|pivot_offset|scale|position|size)\s*=", text, "HUD.tscn: rect_* properties")
    no(r"^v?align\s*=", text, "HUD.tscn: align/valign (horizontal_/vertical_alignment)")
    has(r"^custom_minimum_size\s*=\s*Vector2\(\s*120\s*,\s*32\s*\)", text, "ScoreLabel min size kept")
    has(r"^pivot_offset\s*=", text, "ScoreLabel pivot kept")
    has(r"^offset_left\s*=", text, "layout offsets kept")
    has(r"^horizontal_alignment\s*=", text, "label alignment kept")


def test_script_matches_scene():
    names = set(node_names((ROOT / "scenes" / "HUD.tscn").read_text(encoding="utf-8")))
    missing = dollar_paths(gd(ROOT, "scripts/hud.gd")) - names
    assert not missing, f"hud.gd uses ${sorted(missing)} but HUD.tscn has {sorted(names)}"


def test_project_file_is_godot4():
    text = (ROOT / "project.godot").read_text(encoding="utf-8")
    has(r"^config_version=5\s*$", text, "project.godot config_version=5")
    has(r'^Settings="\*res://scripts/settings\.gd"', text, "Settings autoload kept")
