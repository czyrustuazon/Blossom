"""Hidden acceptance for godot4-port-physics: scripts, scenes and project.godot use Godot 4 APIs,
keep their tuning values, and scripts still match the node names in their scenes."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # the workspace; this folder is copied in as _acceptance/
sys.path.insert(0, str(HERE))
from gdcheck import dollar_paths, gd, has, no, node_names, old_connect  # noqa: E402

COMMON_GODOT3 = [
    (r"^\s*export\b", "Godot 3 `export` keyword"),
    (r"^\s*onready\b", "Godot 3 `onready` keyword"),
    (r"\byield\s*\(", "yield()"),
    (r"\bKinematicBody2D\b", "KinematicBody2D"),
    (r"\bdeg2rad\b|\brad2deg\b", "deg2rad/rad2deg"),
    (r"\brand_range\b", "rand_range"),
    (r"\.instance\s*\(", ".instance()"),
    (r"\bOS\.get_ticks_msec\b", "OS.get_ticks_msec"),
    (r"\bget_slide_count\b", "get_slide_count"),
    (r"\bmove_and_slide\s*\(\s*[^)\s]", "move_and_slide() with arguments"),
    (r"^\s*var\s+velocity\b", "own `velocity` member (CharacterBody2D already has one)"),
]


def _check_common(text: str, name: str):
    for pattern, what in COMMON_GODOT3:
        no(pattern, text, f"{name}: {what}")
    old_connect(text, name)


def test_player_script():
    s = gd(ROOT, "scripts/player.gd")
    _check_common(s, "player.gd")
    has(r"^extends\s+CharacterBody2D\b", s, "player.gd must extend CharacterBody2D")
    has(r"@export\s+var\s+speed\b[^\n]*220", s, "speed stays an exported 220.0")
    has(r"@export\s+var\s+jump_velocity\b[^\n]*-400", s, "jump_velocity stays an exported -400.0")
    has(r"@export_range\(\s*0(\.0)?\s*,\s*2000(\.0)?\s*\)\s*var\s+gravity\b[^\n]*900", s,
        "gravity stays a 0..2000 range export of 900.0")
    has(r"@onready\s+var\s+sprite\b", s, "sprite stays an @onready var")
    has(r"\bmove_and_slide\(\s*\)", s, "move_and_slide() is called")
    has(r"\bget_slide_collision_count\(\)", s, "collisions iterate get_slide_collision_count()")
    no(r"\.collider\b(?!_)", s, "player.gd: KinematicCollision2D.collider property (now get_collider())")
    has(r"\bawait\s+get_tree\(\)\.create_timer\(\s*0\.5\s*\)\.timeout\b", s, "die() awaits the 0.5 s timer")
    has(r"\bhit\.emit\(\)|emit_signal\(\s*\"hit\"\s*\)", s, "hit is still emitted")


def test_enemy_script():
    s = gd(ROOT, "scripts/enemy.gd")
    _check_common(s, "enemy.gd")
    has(r"^extends\s+CharacterBody2D\b", s, "enemy.gd must extend CharacterBody2D")
    has(r"@export\s+var\s+speed\b[^\n]*80", s, "speed stays an exported 80.0")
    has(r"\bdeg_to_rad\(\s*randf_range\(\s*-10\s*,\s*10\s*\)\s*\)", s, "random tilt uses deg_to_rad(randf_range(-10, 10))")
    has(r"screen_exited", s, "still reacts to screen_exited")


def test_main_script():
    s = gd(ROOT, "scripts/main.gd")
    _check_common(s, "main.gd")
    has(r"@export\s+var\s+enemy_scene\s*:\s*PackedScene\b", s, "enemy_scene is a typed PackedScene export")
    has(r"\benemy_scene\.instantiate\(\)", s, "enemies are created with instantiate()")
    has(r"\bTime\.get_ticks_msec\(\)", s, "Time.get_ticks_msec()")
    has(r"\brandf_range\(\s*-40\s*,\s*40\s*\)", s, "spawn offset uses randf_range(-40, 40)")
    has(r"\bawait\s+get_tree\(\)\.create_timer\(\s*1(\.0)?\s*\)\.timeout\b", s, "restart awaits the 1 s timer")
    has(r"\bhit\b", s, "player hit signal still connected")


def test_scenes_use_godot4_node_types():
    old = {"KinematicBody2D", "AnimatedSprite", "Sprite", "VisibilityNotifier2D", "Position2D"}
    want = {"Player.tscn": {"CharacterBody2D", "AnimatedSprite2D"},
            "Enemy.tscn": {"CharacterBody2D", "Sprite2D", "VisibleOnScreenNotifier2D"},
            "Main.tscn": {"Marker2D"}}
    for scene, types in want.items():
        text = (ROOT / "scenes" / scene).read_text(encoding="utf-8")
        found = set(node_names(text).values())
        assert not (found & old), f"{scene}: Godot 3 node types {sorted(found & old)}"
        assert types <= found, f"{scene}: expected {sorted(types)}, has {sorted(found)}"
        no(r'type="Texture"', text, f"{scene}: Texture resource type (Texture2D in Godot 4)")


def test_scripts_match_scene_nodes():
    pairs = {"scripts/player.gd": "Player.tscn", "scripts/enemy.gd": "Enemy.tscn", "scripts/main.gd": "Main.tscn"}
    for script, scene in pairs.items():
        names = set(node_names((ROOT / "scenes" / scene).read_text(encoding="utf-8")))
        missing = dollar_paths(gd(ROOT, script)) - names
        assert not missing, f"{script} uses ${sorted(missing)} but {scene} has {sorted(names)}"


def test_project_file_is_godot4():
    text = (ROOT / "project.godot").read_text(encoding="utf-8")
    has(r"^config_version=5\s*$", text, "project.godot config_version=5")
    has(r'run/main_scene="res://scenes/Main\.tscn"', text, "main scene kept")
