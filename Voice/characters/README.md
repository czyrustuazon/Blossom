# Character voice packs (local weights — gitignored)

Drop one folder per character. The voice service auto-discovers these.

```text
characters/
  <Name>/
    Jpn/   # Japanese RVC: *.pth + *.index
    Eng/   # English RVC: *.pth + *.index
```

Example: `characters/VOICE/Jpn/…` and `characters/VOICE/Eng/…`.

In Companion → Personality, set **Voice pack** to the folder name (`VOICE`).
`presets.yaml` `default_voice` is used when a persona leaves voice_id empty.

Optional override: env `VOICE_CHARACTERS_DIR` pointing at another packs root.
