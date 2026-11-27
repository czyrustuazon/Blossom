"""Builds src/*.c for the 3DS with devkitARM (compile + link to an .elf, warnings as errors)."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEVKITPRO = Path(os.environ.get("DEVKITPRO_WIN") or r"C:\devkitPro")
BIN = DEVKITPRO / "devkitARM" / "bin"
ARCH = ["-march=armv6k", "-mtune=mpcore", "-mfloat-abi=hard", "-mtp=soft"]
LIBS = ["-lcitro2d", "-lcitro3d", "-lctru", "-lm"]


def tool(name: str) -> str:
    exe = BIN / f"arm-none-eabi-{name}.exe"
    if not exe.is_file():
        exe = BIN / f"arm-none-eabi-{name}"
    if not exe.is_file():
        raise RuntimeError(f"devkitARM {name} not found in {BIN} (set DEVKITPRO_WIN)")
    return str(exe)


def build_3ds(out_dir: Path) -> dict[str, set[str]]:
    """Compiles and links src/*.c; returns the undefined symbols of each object file."""
    include = DEVKITPRO / "libctru" / "include"
    objects, undefined = [], {}
    for src in sorted((ROOT / "src").glob("*.c")):
        obj = out_dir / (src.stem + ".o")
        cc = subprocess.run([tool("gcc"), *ARCH, "-O2", "-D__3DS__", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                             "-I", str(include), "-I", "src", "-c", src.relative_to(ROOT).as_posix(), "-o", str(obj)],
                            capture_output=True, text=True, cwd=ROOT)
        assert cc.returncode == 0, f"{src.name}:\n{cc.stderr}"
        objects.append(str(obj))
        nm = subprocess.run([tool("nm"), "-u", str(obj)], capture_output=True, text=True)
        undefined[src.name] = {line.split()[-1] for line in nm.stdout.splitlines() if line.strip()}
    ld = subprocess.run([tool("gcc"), "-specs=3dsx.specs", *ARCH, *objects,
                         "-L", str(DEVKITPRO / "libctru" / "lib"), *LIBS, "-o", str(out_dir / "game.elf")],
                        capture_output=True, text=True)
    assert ld.returncode == 0, ld.stderr
    return undefined
