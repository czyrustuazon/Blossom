from __future__ import annotations

import re
from pathlib import Path

_FENCE_RE = re.compile(r"```([^\n`]*)\n([\s\S]*?)```", re.MULTILINE)
_PATH_RE = re.compile(r"\bpath\s*[=:]\s*[\"']?([^\s\"'`]+)[\"']?", re.IGNORECASE)
_FILE_RE = re.compile(r"\bfile\s*[=:]\s*[\"']?([^\s\"'`]+)[\"']?", re.IGNORECASE)
_LANG_PATH_RE = re.compile(r"^(\w[\w-]*):([^\s`]+)$")


def _path_from_info(info: str) -> str | None:
    info = (info or "").strip()
    m = _PATH_RE.search(info)
    if m:
        return m.group(1).replace("\\", "/")
    m = _FILE_RE.search(info)
    if m:
        return m.group(1).replace("\\", "/")
    m = _LANG_PATH_RE.match(info)
    if m:
        candidate = m.group(2).strip().strip("\"'")
        if "." in candidate or "/" in candidate or "\\" in candidate:
            return candidate.replace("\\", "/")
    return None


def extract_file_writes(response_text: str) -> dict[str, str]:
    writes: dict[str, str] = {}
    for match in _FENCE_RE.finditer(response_text or ""):
        info = match.group(1) or ""
        body = (match.group(2) or "").rstrip("\n")
        path = _path_from_info(info)
        if not path or not body.strip():
            continue
        norm = path.replace("\\", "/")
        writes[norm] = body + "\n"
    return writes


def apply_response_to_workdir(response_text: str, work_dir: Path) -> list[str]:
    """Write path-labeled fences from the model into work_dir. Returns paths written."""
    written: list[str] = []
    for rel, content in extract_file_writes(response_text).items():
        dest = work_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8", newline="\n")
        written.append(rel)
    return written
