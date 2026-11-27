# pong3ds

Two-player Pong for the Nintendo 3DS (libctru, citro2d, devkitARM).

- Left paddle: D-Pad up/down. Right paddle: X/B. START quits.
- `src/game.c`: game logic (plain C, also builds on the PC).
- `src/render.c`: drawing with citro2d on the GPU: net, paddles and ball as rectangles and the score
  as system-font text on the top screen; the controls as text on the bottom screen.
- `src/main.c`: main loop (`C3D_FrameEnd` swaps the buffers).

## Tests

`python -m pytest -q tests` builds the game logic with the host gcc and the whole game with
devkitARM (`C:\devkitPro`, override with `DEVKITPRO_WIN`). No 3DS needed.
