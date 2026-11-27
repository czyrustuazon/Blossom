# HUD Kit

Godot 4.3 HUD and settings we reuse across our small games.

- `scenes/HUD.tscn` + `scripts/hud.gd`: score (pops with a tween when it changes), lives (0..10,
  editable in the inspector, the script also runs in the editor), centre message, Start button and
  difficulty buttons.
- `scripts/settings.gd`: autoload `Settings`; volume and fullscreen saved as JSON in
  `user://settings.json`, volume snapped to 0.05 steps.

`python -m pytest -q tests` runs static checks of the project files (no Godot needed).
