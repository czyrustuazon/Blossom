"""
Resolve local GGUF paths for Blossom.

Paths may be absolute, or relative to Brains/models/ (e.g. coding/foo.gguf).

Coder ladder (tried in order before cloud):
  1. CODER_MODELS=coding/a.gguf,coding/b.gguf   (preferred, fully agnostic)
  2. else CODER_MODEL_PATH (+ optional CODER_ALT_MODEL_PATH)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
load_dotenv(SCRIPT_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

MODELS_DIR = PROJECT_ROOT / "Brains" / "models"

DEFAULT_PERSONA = MODELS_DIR / "conversational" / "Qwen3-8B-Q4_K_M.gguf"
DEFAULT_CODER = MODELS_DIR / "coding" / "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"


@dataclass(frozen=True)
class LocalModel:
    path: Path
    kind: str  # "persona" | "coder"

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def available(self) -> bool:
        return self.path.is_file()


def resolve_model_path(raw: str | Path | None, *, default: Path | None = None) -> Path:
    """Turn env text into an absolute Path under Brains/models when relative."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if default is None:
            raise ValueError("No model path provided")
        return default.resolve()

    text = str(raw).strip().strip('"').strip("'")
    path = Path(text)
    if path.is_file():
        return path.resolve()
    if path.is_absolute():
        return path.resolve()

    under_models = (MODELS_DIR / path).resolve()
    return under_models


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


def persona_model() -> LocalModel:
    raw = os.getenv("PERSONA_MODEL_PATH") or os.getenv("PERSONA_MODEL")
    path = resolve_model_path(raw, default=DEFAULT_PERSONA)
    return LocalModel(path=path, kind="persona")


def coder_ladder(*, available_only: bool = False) -> list[LocalModel]:
    """
    Ordered local coder GGUFs.

    CODER_MODELS wins when set. Otherwise:
      CODER_MODEL_PATH (or default) then optional CODER_ALT_MODEL_PATH.
    """
    models_raw = os.getenv("CODER_MODELS", "").strip()
    paths: list[Path] = []

    if models_raw:
        for entry in _split_csv(models_raw):
            paths.append(resolve_model_path(entry))
    else:
        primary = os.getenv("CODER_MODEL_PATH") or os.getenv("CODER_MODEL")
        paths.append(resolve_model_path(primary, default=DEFAULT_CODER))
        alt = os.getenv("CODER_ALT_MODEL_PATH") or os.getenv("CODER_ALT_MODEL")
        if alt and alt.strip():
            paths.append(resolve_model_path(alt))

    seen: set[str] = set()
    out: list[LocalModel] = []
    for path in paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        model = LocalModel(path=path, kind="coder")
        if available_only and not model.available:
            continue
        out.append(model)
    return out


def primary_coder() -> LocalModel:
    """Prefer the first GGUF that exists on disk (hybrid 70B may still be downloading)."""
    available = coder_ladder(available_only=True)
    if available:
        return available[0]
    ladder = coder_ladder(available_only=False)
    return ladder[0] if ladder else LocalModel(path=DEFAULT_CODER, kind="coder")


# Coder picker (Blossom Assistant switches coders per request with `blossom_coder`).
# Tool-call mode each coder scored best with on the refactor eval (2026-11-24):
# Qwen3.8-27B fence 25/27 (native 7/9), Qwen3.6-35B-A3B native 22/27 (fence 4/9), Nemotron fence.
# "substring=native|fence;…" — first match wins, unmatched files use "fence".
DEFAULT_CODER_TOOL_MODES = "Qwen3.6=native;Qwen3.8=fence;Nemotron=fence"
_KNOWN_CODER_LABELS = (
    ("Qwen3.8-27B", "Qwen3.8 27B"),
    ("Qwen3.6-35B-A3B", "Qwen3.6 35B-A3B"),
    ("Nemotron-3.5-Lightning", "Nemotron 3.5 Lightning 30B"),
    ("Qwen3-Coder-30B-A3B", "Qwen3-Coder 30B-A3B"),
    ("Devstral-Small-2", "Devstral Small 2 24B"),
    ("DeepSeek-Coder-V2-Lite", "DeepSeek-Coder-V2 Lite"),
)


def coder_id(path: Path) -> str:
    """Stable id for a coder GGUF: the file stem, lower case."""
    return path.stem.lower()


def coder_label(path: Path) -> str:
    for needle, label in _KNOWN_CODER_LABELS:
        if needle.lower() in path.name.lower():
            return label
    return path.stem


# What each coder is good at, from the real-extension refactor evals (9 tasks, 2026-11-23..25):
# (file-name needle, short strength for menus, longer note for tooltips).
_KNOWN_CODER_NOTES = (
    ("Qwen3.8-27B", "most accurate · slower",
     "Best for multi-file refactors and careful changes: 25/27 refactor tasks passed (93%). "
     "Dense 27B, ~40 tok/s at 64k, ~31 at 128k; 256k only as a slow last resort (~16 tok/s). "
     "Median ~7 min per task."),
    ("Qwen3.6-35B-A3B", "fast · good accuracy · best for 256k",
     "Best for quick edits, questions, fast iteration and very large inputs: 22/27 refactor tasks "
     "(81%) with native tool calls; keeps ~63 tok/s even at the full 256k window. "
     "Mixture-of-experts, median ~3 min per task."),
    ("Nemotron-3.5-Lightning", "long context · least accurate",
     "Trained for up to 1M tokens (launched at up to 262k here), but weakest at refactors: "
     "~42% of tasks passed. Qwen3.6 now covers 256k faster and more accurately."),
    ("Qwen3-Coder-30B-A3B", "fast · weak at refactors",
     "7/27 refactor tasks passed in the 2026-11-24 A/B; fast but loses track in long agent loops."),
    ("Devstral-Small-2", "weak at agent loops",
     "2/9 refactor tasks passed (fence and native)."),
)


def coder_notes(path: Path, rules: str | None = None) -> tuple[str, str]:
    """(short strength, longer note) for a coder file. CODER_NOTES="needle=short|long;…" wins."""
    raw = rules if rules is not None else os.getenv("CODER_NOTES", "")
    for rule in raw.split(";"):
        if "=" not in rule:
            continue
        needle, text = (part.strip() for part in rule.split("=", 1))
        if needle and needle.lower() in path.name.lower():
            short, _, long = text.partition("|")
            return short.strip(), (long.strip() or short.strip())
    for needle, short, long in _KNOWN_CODER_NOTES:
        if needle.lower() in path.name.lower():
            return short, long
    return "", ""


def coder_tool_mode(path: Path, rules: str | None = None) -> str:
    raw = rules if rules is not None else os.getenv("CODER_TOOL_MODES", DEFAULT_CODER_TOOL_MODES)
    for rule in raw.split(";"):
        if "=" not in rule:
            continue
        needle, mode = (part.strip() for part in rule.split("=", 1))
        if needle and needle.lower() in path.name.lower() and mode.lower() in {"native", "fence"}:
            return mode.lower()
    return "fence"


def match_coder(choice: str | None, ladder: list[LocalModel]) -> LocalModel | None:
    """The ladder entry a host's choice names: id, file name, or a unique substring of it."""
    text = (choice or "").strip().lower()
    if not text:
        return None
    for model in ladder:
        if text in {coder_id(model.path), model.name.lower()}:
            return model
    hits = [m for m in ladder if text in m.name.lower()]
    return hits[0] if len(hits) == 1 else None


def order_ladder(ladder: list[LocalModel], choice: str | None) -> list[LocalModel]:
    """The chosen coder first, the rest of the ladder after it as fallbacks."""
    chosen = match_coder(choice, ladder)
    if chosen is None:
        return list(ladder)
    return [chosen] + [m for m in ladder if m is not chosen]


def coder_catalog() -> list[dict]:
    """Coders a host can pick from: every CODER_MODELS entry; the first available is the default."""
    ladder = coder_ladder(available_only=False)
    default = next((m for m in ladder if m.available), None)
    out = []
    for m in ladder:
        strength, note = coder_notes(m.path)
        out.append(
            {
                "id": coder_id(m.path),
                "label": coder_label(m.path),
                "file": m.name,
                "available": m.available,
                "tool_mode": coder_tool_mode(m.path),
                "default": m is default,
                "strength": strength,
                "note": note,
            }
        )
    return out


def any_coder_available() -> bool:
    return bool(coder_ladder(available_only=True))


# Persona slot field. Empty brain id keeps PERSONA_MODEL_PATH (Qwen).
BOLT_BRAIN_ID = "bolt"


def persona_alt_model() -> LocalModel | None:
    """Second conversational GGUF (Nemotron Bolt). Unset means there is no alt brain."""
    raw = os.getenv("PERSONA_ALT_MODEL_PATH", "").strip()
    if not raw:
        return None
    return LocalModel(path=resolve_model_path(raw), kind="persona")


def _brain_label(path: Path) -> str:
    name = path.name
    if "Bolt-E4B" in name:
        return "Nemotron Bolt E4B"
    if "Qwen3-14B" in name or "Qwen_Qwen3-14B" in name:
        return "Qwen3 14B"
    return path.stem


def persona_brain_catalog() -> list[dict]:
    """Brains the personality panel can assign. id '' is the default persona GGUF."""
    main = persona_model()
    brains = [
        {
            "id": "",
            "label": _brain_label(main.path),
            "path": str(main.path),
            "available": main.available,
        }
    ]
    alt = persona_alt_model()
    if alt is not None:
        brains.append(
            {
                "id": BOLT_BRAIN_ID,
                "label": _brain_label(alt.path),
                "path": str(alt.path),
                "available": alt.available,
            }
        )
    return brains


def persona_brain_path(brain_id: str | None) -> Path:
    """GGUF for a persona slot. A missing Bolt file falls back to the default persona."""
    if (brain_id or "").strip() == BOLT_BRAIN_ID:
        alt = persona_alt_model()
        if alt is not None and alt.available:
            return alt.path.resolve()
    return persona_model().path.resolve()
