# pong3ds

Two-player Pong for the Nintendo 3DS (libctru, devkitARM).

- Left paddle: D-Pad up/down. Right paddle: X/B. START quits.
- `src/game.c`: game logic (plain C, also builds on the PC).
- `src/render.c`: drawing. The top screen is drawn by writing pixels into the framebuffer on the
  CPU; the bottom screen shows the controls with the libctru console.
- `src/main.c`: main loop.

## Tests

`python -m pytest -q tests` builds the game logic with the host gcc and the whole game with
devkitARM (`C:\devkitPro`, override with `DEVKITPRO_WIN`). No 3DS needed.
