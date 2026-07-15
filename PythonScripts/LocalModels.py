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
    ladder = coder_ladder(available_only=False)
    return ladder[0] if ladder else LocalModel(path=DEFAULT_CODER, kind="coder")


def any_coder_available() -> bool:
    return bool(coder_ladder(available_only=True))
