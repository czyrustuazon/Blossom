"""Hidden acceptance for 3ds-citro2d-port: the game draws with citro2d/citro3d on both screens, no CPU
framebuffer or console use is left, text buffers are managed correctly, game logic is untouched."""
import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # the workspace; this folder is copied in as _acceptance/
DEVKITPRO = Path(os.environ.get("DEVKITPRO_WIN") or r"C:\devkitPro")
BIN = DEVKITPRO / "devkitARM" / "bin"
ARCH = ["-march=armv6k", "-mtune=mpcore", "-mfloat-abi=hard", "-mtp=soft"]

REQUIRED = {
    "C3D_Init", "C3D_Fini", "C2D_Init", "C2D_Prepare", "C2D_Fini", "C2D_CreateScreenTarget",
    "C3D_FrameBegin", "C3D_FrameEnd", "C2D_TargetClear",
    "C3D_FrameDrawOn",      # C2D_SceneBegin
    "C2D_DrawRectangle",    # C2D_DrawRectSolid / C2D_DrawRectangle
    "C2D_DrawText", "C2D_TextBufNew", "C2D_TextBufDelete",
}
FORBIDDEN = {"gfxGetFramebuffer", "gfxSwapBuffers", "gfxSwapBuffersGpu", "gfxScreenSwapBuffers",
             "gfxFlushBuffers", "consoleInit"}


def _tool(name: str) -> str:
    for exe in (BIN / f"arm-none-eabi-{name}.exe", BIN / f"arm-none-eabi-{name}"):
        if exe.is_file():
            return str(exe)
    raise AssertionError(f"devkitARM {name} not found in {BIN}")


def _undefined_symbols(tmp: Path) -> set[str]:
    objects, syms = [], set()
    for src in sorted((ROOT / "src").glob("*.c")):
        obj = tmp / (src.stem + ".o")
        cc = subprocess.run([_tool("gcc"), *ARCH, "-O2", "-D__3DS__", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                             "-I", str(DEVKITPRO / "libctru" / "include"), "-I", "src", "-c",
                             src.relative_to(ROOT).as_posix(), "-o", str(obj)], capture_output=True, text=True, cwd=ROOT)
        assert cc.returncode == 0, f"{src.name}:\n{cc.stderr}"
        objects.append(str(obj))
        nm = subprocess.run([_tool("nm"), "-u", str(obj)], capture_output=True, text=True)
        syms |= {line.split()[-1] for line in nm.stdout.splitlines() if line.strip()}
    ld = subprocess.run([_tool("gcc"), "-specs=3dsx.specs", *ARCH, *objects, "-L", str(DEVKITPRO / "libctru" / "lib"),
                         "-lcitro2d", "-lcitro3d", "-lctru", "-lm", "-o", str(tmp / "game.elf")],
                        capture_output=True, text=True)
    assert ld.returncode == 0, ld.stderr
    return syms


def _code(text: str, keep_strings: bool = False) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text if keep_strings else re.sub(r'"(?:\\.|[^"\\])*"', '""', text)


def _all_code(keep_strings: bool = False) -> str:
    return "\n".join(_code(p.read_text(encoding="utf-8"), keep_strings) for p in sorted((ROOT / "src").glob("*.[ch]")))


def _function_body(code: str, name: str) -> str:
    m = re.search(r"\b" + name + r"\s*\([^;{]*\)\s*\{", code)
    assert m, f"{name}() not found"
    depth, i = 1, m.end()
    while depth and i < len(code):
        depth += {"{": 1, "}": -1}.get(code[i], 0)
        i += 1
    return code[m.end():i]


def test_uses_citro2d_and_no_cpu_framebuffer(tmp_path: Path):
    syms = _undefined_symbols(tmp_path)
    missing = REQUIRED - syms
    assert not missing, f"never called: {sorted(missing)}"
    assert syms & {"C2D_TextParse", "C2D_TextFontParse"}, "score/help text is not parsed with citro2d"
    left = FORBIDDEN & syms
    assert not left, f"old framebuffer/console path still used: {sorted(left)}"


def test_both_screens_are_citro2d_targets():
    code = _all_code()
    assert re.search(r"C2D_CreateScreenTarget\s*\(\s*GFX_TOP\b", code), "no top-screen target"
    assert re.search(r"C2D_CreateScreenTarget\s*\(\s*GFX_BOTTOM\b", code), "no bottom-screen target"
    assert "START: quit" in _all_code(keep_strings=True), "help text is gone"


def test_text_buffers_are_managed():
    code = _all_code()
    frame = _function_body(code, "render_frame")
    if re.search(r"\bC2D_Text(?:Font)?Parse\s*\(", frame):
        assert re.search(r"\bC2D_TextBufClear\s*\(", frame) or re.search(r"\bC2D_TextBufDelete\s*\(", frame), \
            "text is parsed every frame into a buffer that is never cleared (it fills up)"
    if re.search(r"\bC2D_TextBufNew\s*\(", frame):
        assert re.search(r"\bC2D_TextBufDelete\s*\(", frame), "a text buffer is created every frame and leaked"
    new = len(re.findall(r"\bC2D_TextBufNew\s*\(", code))
    delete = len(re.findall(r"\bC2D_TextBufDelete\s*\(", code))
    assert delete >= new, f"{new} C2D_TextBufNew vs {delete} C2D_TextBufDelete"


def test_shutdown_order():
    code = _all_code()
    i2, i3 = code.find("C2D_Fini"), code.find("C3D_Fini")
    assert 0 <= i2 < i3, "C2D_Fini must run before C3D_Fini"
    main = _function_body(code, "main")
    assert main.find("render_exit") < main.find("gfxExit"), "render_exit must run before gfxExit"


def test_game_logic_untouched():
    for name in ("game.c", "game.h"):
        now = (ROOT / "src" / name).read_text(encoding="utf-8").replace("\r\n", "\n")
        orig = (HERE / "orig" / name).read_text(encoding="utf-8").replace("\r\n", "\n")
        assert now == orig, f"src/{name} was changed"
