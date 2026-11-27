"""Helpers for static Godot 4 checks of GDScript and .tscn files."""
import re
from pathlib import Path


def strip_comments(src: str) -> str:
    """GDScript without # comments (quotes respected)."""
    out = []
    for line in src.splitlines():
        quote, cut = None, len(line)
        for i, ch in enumerate(line):
            if quote:
                if ch == "\\":
                    continue
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "#":
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def gd(root: Path, rel: str) -> str:
    path = root / rel
    assert path.is_file(), f"{rel} is missing"
    return strip_comments(path.read_text(encoding="utf-8"))


def no(pattern: str, text: str, what: str, flags=re.M):
    m = re.search(pattern, text, flags)
    assert not m, f"{what}: found {m.group(0)!r}"


def has(pattern: str, text: str, what: str, flags=re.M):
    assert re.search(pattern, text, flags), what


def node_names(scene_text: str) -> dict[str, str]:
    """name -> type for the scene's nodes (instanced nodes get type '')."""
    return {m.group(1): (m.group(2) or "")
            for m in re.finditer(r'^\[node name="([^"]+)"(?:\s+type="([^"]+)")?', scene_text, re.M)}


def dollar_paths(script: str) -> set[str]:
    return set(re.findall(r'\$"?([A-Za-z_][A-Za-z0-9_]*)', script))


def old_connect(text: str, what: str):
    no(r'\bconnect\(\s*"[^"]+"\s*,\s*self\s*,', text, f"{what}: Godot 3 connect(signal, self, \"method\")")
