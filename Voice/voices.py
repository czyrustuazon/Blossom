"""Discover character voice packs under Voice/characters/<id>/{Jpn,Eng}/."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def characters_root(root: Path | None = None) -> Path:
    """Pack directory: VOICE_CHARACTERS_DIR, else <Voice>/characters."""
    override = os.getenv("VOICE_CHARACTERS_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (root or ROOT) / "characters"


_SKIP_DIRS = frozenset(
    {
        ".venv",
        "model_assets",
        "__pycache__",
        ".git",
        "characters",  # if someone points discovery at Voice/ by mistake
    }
)

_LOCALE_DIRS = {
    "ja": ("Jpn", "jpn", "JA", "ja", "JP", "jp"),
    "en": ("Eng", "eng", "EN", "en", "US", "us"),
}


@dataclass(frozen=True)
class LocalePack:
    model: Path
    index: Path


@dataclass(frozen=True)
class VoicePack:
    id: str
    path: Path
    ja: LocalePack | None
    en: LocalePack | None

    @property
    def locales(self) -> list[str]:
        out: list[str] = []
        if self.ja:
            out.append("ja")
        if self.en:
            out.append("en")
        return out

    def for_locale(self, locale: str) -> LocalePack | None:
        return self.en if locale == "en" else self.ja


def _pick_rvc_pair(folder: Path) -> LocalePack | None:
    if not folder.is_dir():
        return None
    pths = sorted(folder.glob("*.pth"))
    idxs = sorted(folder.glob("*.index"))
    if not pths or not idxs:
        return None

    def prefer(files: list[Path], name: str) -> Path:
        for f in files:
            if f.name.lower() == name:
                return f
        return files[0]

    model = prefer(pths, "model.pth")
    # Prefer index that shares stem with model, else model.index, else first.
    stem = model.stem.lower()
    matched = [i for i in idxs if i.stem.lower() == stem or i.stem.lower().startswith(stem)]
    if matched:
        index = matched[0]
    else:
        index = prefer(idxs, "model.index")
    return LocalePack(model=model, index=index)


def _locale_subdir(character_dir: Path, locale: str) -> Path | None:
    for name in _LOCALE_DIRS[locale]:
        candidate = character_dir / name
        if candidate.is_dir():
            return candidate
    return None


def discover_voices(characters_dir: Path | None = None) -> list[VoicePack]:
    """Scan Voice/characters/<id>/{Jpn,Eng}/ for .pth + .index pairs."""
    base = characters_dir or characters_root()
    packs: list[VoicePack] = []
    if not base.is_dir():
        return packs
    for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name in _SKIP_DIRS:
            continue
        if child.name.startswith("."):
            continue
        ja_dir = _locale_subdir(child, "ja")
        en_dir = _locale_subdir(child, "en")
        ja = _pick_rvc_pair(ja_dir) if ja_dir else None
        en = _pick_rvc_pair(en_dir) if en_dir else None
        if not ja and not en:
            continue
        packs.append(VoicePack(id=child.name, path=child, ja=ja, en=en))
    return packs


def resolve_voice_id(requested: str | None, packs: list[VoicePack], default: str | None = None) -> str | None:
    """Case-insensitive match; fall back to default folder name, then first pack."""
    if not packs:
        return None
    by_lower = {p.id.lower(): p.id for p in packs}
    if requested:
        key = requested.strip()
        if key in by_lower.values():
            return key
        if key.lower() in by_lower:
            return by_lower[key.lower()]
    if default:
        d = default.strip()
        if d in by_lower.values():
            return d
        if d.lower() in by_lower:
            return by_lower[d.lower()]
    return packs[0].id


def slug_guess_from_name(name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "", (name or "").strip())
    return base or ""
