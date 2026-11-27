"""Hidden acceptance for 3ds-ndsp-sfx: src/sound.c plays the romfs effects with NDSP correctly
(checked on the host against a recording mock of libctru) and the app still builds with devkitARM."""
import os
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # the workspace; this folder is copied in as _acceptance/
DEVKITPRO = Path(os.environ.get("DEVKITPRO_WIN") or r"C:\devkitPro")
INCLUDE = DEVKITPRO / "libctru" / "include"
BIN = DEVKITPRO / "devkitARM" / "bin"
ARCH = ["-march=armv6k", "-mtune=mpcore", "-mfloat-abi=hard", "-mtp=soft"]


def _host_driver(tmp: Path) -> Path:
    gcc = shutil.which("gcc")
    assert gcc, "gcc not found on PATH"
    exe = tmp / "sound_driver.exe"
    b = subprocess.run([gcc, "-std=gnu11", "-I", "_acceptance/mock", "-I", INCLUDE.as_posix(), "-I", "src",
                        "-o", exe.as_posix(), "src/sound.c", "_acceptance/mock/mock_ndsp.c",
                        "_acceptance/sound_driver.c"], capture_output=True, text=True, cwd=ROOT)
    assert b.returncode == 0, "sound.c does not build against libctru's NDSP API:\n" + b.stderr[-4000:]
    return exe


def _run(exe: Path, scenario: str) -> list[str]:
    env = dict(os.environ, MOCK_ROMFS=str(ROOT / "romfs"))
    p = subprocess.run([str(exe), scenario], capture_output=True, text=True, timeout=60, env=env)
    lines = p.stdout.splitlines()
    assert any(line.startswith("DONE") for line in lines), f"driver crashed (exit {p.returncode}):\n{p.stdout}{p.stderr}"
    return [line for line in lines if line.startswith("FAIL")]


def test_plays_effects_with_ndsp(tmp_path: Path):
    fails = _run(_host_driver(tmp_path), "ok")
    assert not fails, "\n".join(fails)


def test_runs_muted_without_dsp_firmware(tmp_path: Path):
    fails = _run(_host_driver(tmp_path), "nofirm")
    assert not fails, "\n".join(fails)


def _tool(name: str) -> str:
    for exe in (BIN / f"arm-none-eabi-{name}.exe", BIN / f"arm-none-eabi-{name}"):
        if exe.is_file():
            return str(exe)
    raise AssertionError(f"devkitARM {name} not found in {BIN}")


def test_3ds_build_uses_ndsp(tmp_path: Path):
    objects, syms = [], set()
    for src in sorted((ROOT / "src").glob("*.c")):
        obj = tmp_path / (src.stem + ".o")
        cc = subprocess.run([_tool("gcc"), *ARCH, "-O2", "-D__3DS__", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                             "-I", str(INCLUDE), "-I", "src", "-c", src.relative_to(ROOT).as_posix(), "-o", str(obj)],
                            capture_output=True, text=True, cwd=ROOT)
        assert cc.returncode == 0, f"{src.name}:\n{cc.stderr}"
        objects.append(str(obj))
        nm = subprocess.run([_tool("nm"), "-u", str(obj)], capture_output=True, text=True)
        syms |= {line.split()[-1] for line in nm.stdout.splitlines() if line.strip()}
    ld = subprocess.run([_tool("gcc"), "-specs=3dsx.specs", *ARCH, *objects, "-L", str(DEVKITPRO / "libctru" / "lib"),
                         "-lctru", "-lm", "-o", str(tmp_path / "app.elf")], capture_output=True, text=True)
    assert ld.returncode == 0, ld.stderr
    assert {"ndspInit", "ndspExit", "ndspChnWaveBufAdd", "DSP_FlushDataCache"} <= syms, sorted(syms)
    assert not {s for s in syms if s.startswith("csnd")}, "uses CSND instead of NDSP"
