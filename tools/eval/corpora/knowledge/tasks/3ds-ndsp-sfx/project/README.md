# sfxtest

Sound-effect test app for the Nintendo 3DS (libctru, devkitARM). A plays the bounce effect, B the
score effect, START quits.

- `src/sound.c`: sound effects (`sound.h` interface). Not written yet: the app runs muted.
- `romfs/sfx/*.pcm`: the effects, raw signed 16-bit little-endian mono PCM at 22050 Hz. The romfs
  folder is packed into the .3dsx and read at run time as `romfs:/sfx/...`.
- `src/main.c`: main loop.

## Tests

`python -m pytest -q tests` builds the app with devkitARM (`C:\devkitPro`, override with
`DEVKITPRO_WIN`). No 3DS needed.
