"""Hidden acceptance for c-split-module: util.c/util.h are split into strutil and mathutil,
each file includes only what it uses, private helpers stay static, and nothing changed
behaviour. Builds with -Wmissing-prototypes so every public function must be declared in the
header its .c file includes."""
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # the workspace; this folder is copied in as _acceptance/
SRC = ROOT / "src"

STR_FUNCS = ("str_trim", "str_count_words", "str_to_upper")
MATH_FUNCS = ("clamp_int", "mean_int", "median_int")


def _code(path: Path) -> str:
    src = path.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", " ", src)


def _includes(path: Path) -> set[str]:
    return set(re.findall(r'#\s*include\s*"([^"]+)"', _code(path)))


def _declares(path: Path, name: str) -> bool:
    return re.search(r"\b" + name + r"\s*\(", _code(path)) is not None


def _defines(path: Path, name: str) -> bool:
    # A definition: the name followed by a parameter list and an opening brace.
    return re.search(r"\b" + name + r"\s*\([^;{)]*\)\s*\{", _code(path), flags=re.S) is not None


def test_old_module_removed_new_ones_exist():
    assert not (SRC / "util.c").exists(), "src/util.c should be gone"
    assert not (SRC / "util.h").exists(), "src/util.h should be gone"
    for name in ("strutil.c", "strutil.h", "mathutil.c", "mathutil.h"):
        assert (SRC / name).exists(), f"src/{name} missing"


def test_headers_declare_only_their_own_functions():
    sh, mh = SRC / "strutil.h", SRC / "mathutil.h"
    for f in STR_FUNCS:
        assert _declares(sh, f), f"strutil.h does not declare {f}"
        assert not _declares(mh, f), f"mathutil.h declares string function {f}"
    for f in MATH_FUNCS:
        assert _declares(mh, f), f"mathutil.h does not declare {f}"
        assert not _declares(sh, f), f"strutil.h declares math function {f}"
    assert "UTIL_MAX_SAMPLES" in _code(mh)
    for h in (sh, mh):
        code = _code(h)
        assert re.search(r"#\s*ifndef\s+\w+", code) or "#pragma once" in code, f"{h.name} has no include guard"


def test_definitions_live_in_the_right_file():
    for f in STR_FUNCS:
        assert _defines(SRC / "strutil.c", f), f"{f} is not defined in strutil.c"
        assert not _defines(SRC / "mathutil.c", f)
    for f in MATH_FUNCS:
        assert _defines(SRC / "mathutil.c", f), f"{f} is not defined in mathutil.c"
        assert not _defines(SRC / "strutil.c", f)


def test_private_helpers_stay_static_and_hidden():
    assert re.search(r"\bstatic\s+int\s+is_space\s*\(", _code(SRC / "strutil.c")), "is_space must stay static in strutil.c"
    assert re.search(r"\bstatic\s+int\s+cmp_int\s*\(", _code(SRC / "mathutil.c")), "cmp_int must stay static in mathutil.c"
    for h in SRC.glob("*.h"):
        assert not _declares(h, "is_space") and not _declares(h, "cmp_int"), f"{h.name} exposes a private helper"


def test_each_file_includes_only_what_it_needs():
    for path in list(SRC.glob("*.[ch]")) + [ROOT / "tests" / "driver.c"]:
        assert "util.h" not in _includes(path), f"{path.name} still includes util.h"
    assert "strutil.h" in _includes(SRC / "strutil.c")
    assert "mathutil.h" in _includes(SRC / "mathutil.c")
    assert "mathutil.h" in _includes(SRC / "grades.c")
    assert "strutil.h" not in _includes(SRC / "grades.c"), "grades.c uses no string helpers"
    assert {"strutil.h", "mathutil.h"} <= _includes(SRC / "wordcount.c")
    assert "mathutil.h" not in _includes(SRC / "strutil.c")
    assert "strutil.h" not in _includes(SRC / "mathutil.c")


def test_strict_build_and_behaviour(tmp_path):
    gcc = shutil.which("gcc")
    assert gcc, "gcc not found on PATH"
    exe = tmp_path / "accept.exe"
    sources = sorted(p.relative_to(ROOT).as_posix() for p in SRC.glob("*.c")) + ["tests/driver.c"]
    build = subprocess.run(
        [gcc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wmissing-prototypes",
         "-Wmissing-declarations", "-Isrc", "-o", exe.as_posix(), *sources],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert build.returncode == 0, build.stderr
    out = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30).stdout.splitlines()
    for want in ("lines 2 words 9 mean 4", "trimmed [the quick brown fox]", "heading [CHAPTER ONE]",
                 "mean 69 median 88 clamped 100 0", "empty 0 0", "clamp 0 5 9",
                 "count 3 upper [ONE TWO  THREE]"):
        assert want in out, (want, out)


def test_readme_describes_new_layout():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "strutil" in readme and "mathutil" in readme
    assert "util.c" not in readme.replace("strutil.c", "").replace("mathutil.c", "")
