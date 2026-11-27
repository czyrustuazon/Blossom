# Dodger

Small Godot 4.3 platformer: run and jump over the enemies that roll in from the right. Each spawned
enemy scores a point; touching one ends the run and restarts the scene.

- `scenes/Main.tscn` + `scripts/main.gd`: spawning, score, restart.
- `scenes/Player.tscn` + `scripts/player.gd`: movement (CharacterBody2D; arrows, Space/Enter to jump).
- `scenes/Enemy.tscn` + `scripts/enemy.gd`: enemies.

`python -m pytest -q tests` runs static checks of the project files (no Godot needed).
