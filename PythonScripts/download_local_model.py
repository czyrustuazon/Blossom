"""
Download a GGUF into Brains/models/<role>/ for local Blossom use.

Examples:
  python download_local_model.py --preset deepseek-coder-v2-lite
  python download_local_model.py --role coding --repo bartowski/Foo-GGUF --file Foo-Q4_K_M.gguf
  python download_local_model.py --list-presets
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BRAINS_DIR = PROJECT_ROOT / "Brains"
MODELS_DIR = BRAINS_DIR / "models"
PRESETS_PATH = BRAINS_DIR / "model-presets.json"


def _load_presets() -> dict:
    if not PRESETS_PATH.is_file():
        return {}
    return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))


def _print_env_hint(role: str, rel_path: str, preset: dict | None = None) -> None:
    print()
    print("Download complete. Point .env at this file, then restart ChatRouter:")
    print()
    if role == "conversational":
        print(f"  PERSONA_MODEL_PATH={rel_path}")
    elif preset and preset.get("env_key") == "CODER_ALT_MODEL_PATH":
        print(f"  CODER_ALT_MODEL_PATH={rel_path}")
        print("  # or fold into a ladder:")
        print(f"  # CODER_MODELS=coding/<primary>.gguf,{rel_path}")
    else:
        print(f"  CODER_MODEL_PATH={rel_path}")
        print("  # or multi-coder ladder:")
        print(f"  # CODER_MODELS={rel_path},coding/<alt>.gguf")
    print()


def download(repo: str, filename: str, dest_dir: Path) -> Path:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise SystemExit(
            "huggingface_hub is required. From PythonScripts:\n"
            "  pip install huggingface_hub\n"
        ) from exc

    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {filename}")
    print(f"  from {repo}")
    print(f"  into {dest_dir}")
    path = hf_hub_download(
        repo_id=repo,
        filename=filename,
        local_dir=str(dest_dir),
    )
    return Path(path).resolve()


def main() -> int:
    presets = _load_presets()
    parser = argparse.ArgumentParser(description="Add a local GGUF under Brains/models/")
    parser.add_argument("--preset", help="Name from Brains/model-presets.json")
    parser.add_argument(
        "--role",
        choices=("conversational", "coding"),
        help="Subfolder under Brains/models/",
    )
    parser.add_argument("--repo", help="Hugging Face repo id with GGUF files")
    parser.add_argument("--file", help="Exact .gguf filename inside the repo")
    parser.add_argument(
        "--list-presets",
        action="store_true",
        help="List known presets and exit",
    )
    args = parser.parse_args()

    if args.list_presets:
        if not presets:
            print(f"No presets found at {PRESETS_PATH}")
            return 1
        for name, meta in presets.items():
            print(f"{name}")
            print(f"  role={meta.get('role')} repo={meta.get('repo')}")
            print(f"  file={meta.get('file')}")
        return 0

    preset_meta: dict | None = None
    if args.preset:
        if args.preset not in presets:
            print(f"Unknown preset '{args.preset}'. Known: {', '.join(presets) or '(none)'}")
            return 1
        preset_meta = presets[args.preset]
        role = str(preset_meta["role"])
        repo = str(preset_meta["repo"])
        filename = str(preset_meta["file"])
    else:
        if not (args.role and args.repo and args.file):
            parser.error("Provide --preset, or all of --role --repo --file")
        role = args.role
        repo = args.repo
        filename = args.file

    if not filename.lower().endswith(".gguf"):
        print("Only .gguf files are supported for llama-server.")
        return 1

    dest_dir = MODELS_DIR / role
    out = download(repo, filename, dest_dir)
    rel = f"{role}/{out.name}"
    print(f"Saved: {out}")
    _print_env_hint(role, rel, preset_meta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
