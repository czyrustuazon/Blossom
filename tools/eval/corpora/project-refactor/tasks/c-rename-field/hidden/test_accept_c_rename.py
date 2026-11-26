"""Hidden acceptance for c-rename-field: struct item's `qty` is now `quantity` everywhere,
struct order_line's own `qty` is untouched, behaviour and the CSV report follow the rename."""
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # the workspace; this folder is copied in as _acceptance/


def _code(path: Path) -> str:
    """Source with comments and string literals blanked."""
    src = path.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"//[^\n]*", " ", src)
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', src)


def _struct_body(path: Path, name: str) -> str:
    m = re.search(r"struct\s+" + name + r"\s*\{(.*?)\}\s*;", _code(path), flags=re.S)
    assert m, f"struct {name} not found in {path.name}"
    return m.group(1)


def _run_driver(tmp_path):
    gcc = shutil.which("gcc")
    assert gcc, "gcc not found on PATH"
    exe = tmp_path / "accept.exe"
    sources = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "src").glob("*.c"))
    build = subprocess.run(
        [gcc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Isrc", "-o", exe.as_posix(),
         *sources, "_acceptance/accept_driver.c"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return run.stdout.splitlines()


def test_item_field_renamed():
    body = _struct_body(ROOT / "src" / "item.h", "item")
    assert re.search(r"\bint\s+quantity\s*;", body), body
    assert not re.search(r"\bqty\b", body), "struct item still has qty"


def test_order_line_keeps_qty():
    body = _struct_body(ROOT / "src" / "order.h", "order_line")
    assert re.search(r"\bint\s+qty\s*;", body), "struct order_line.qty must not be renamed"
    assert "quantity" not in body


def test_no_alias_for_old_name():
    for path in list((ROOT / "src").glob("*.[ch]")) + [ROOT / "tests" / "driver.c"]:
        code = _code(path)
        assert not re.search(r"#\s*define\s+qty\b", code), f"{path.name} aliases qty"
        assert not re.search(r"\bunion\b", code), f"{path.name} adds a union alias"


def test_project_tests_follow_rename():
    code = _code(ROOT / "tests" / "driver.c")
    assert "washer->quantity" in code
    assert not re.search(r"(washer|\))->qty\b", code), "driver still reads item->qty"


def test_behaviour_and_csv(tmp_path):
    out = _run_driver(tmp_path)
    assert "empty_before 0" in out
    assert "short 0" in out
    assert "left 1" in out
    assert "take 1" in out
    assert "empty_after 1" in out
    assert "value 1000" in out
    assert "offset_ok 1" in out
    assert "old_column -1" in out, "report_field_offset still accepts the old column name"
    start = next(i for i, line in enumerate(out) if line.startswith("name,"))
    assert out[start] == "name,quantity,price_cents"
    assert out[start + 1:] == ["cog,0,250"]


def test_readme_updated():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    item_line = next(line for line in readme.splitlines() if "struct item" in line)
    assert "quantity" in item_line and "qty" not in item_line, item_line
    order_line = next(line for line in readme.splitlines() if "struct order_line" in line)
    assert "qty" in order_line, "README's struct order_line entry must keep qty"
    assert "name,quantity,price_cents" in readme
    assert "name,qty," not in readme
    assert "it->qty" not in readme
