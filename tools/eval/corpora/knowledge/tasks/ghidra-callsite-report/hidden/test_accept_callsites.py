"""Hidden acceptance for ghidra-callsite-report: CallSiteReport.java's call sites match the direct
call instructions objdump finds (repeated calls, import thunk calls, no data references)."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # the workspace; this folder is copied in as _acceptance/
GHIDRA = Path(os.environ.get("GHIDRA_INSTALL_DIR") or r"C:\Program Files\ghidra_12.1.2")


def _build(tmp: Path) -> Path:
    gcc = shutil.which("gcc")
    assert gcc, "gcc not found on PATH"
    src = tmp / "sample_hidden.c"
    shutil.copy(HERE / "sample_hidden.c", src)
    exe = tmp / "sample_hidden.exe"
    b = subprocess.run([gcc, "-O1", "-o", exe.name, src.name], capture_output=True, text=True, cwd=tmp)
    assert b.returncode == 0, b.stderr
    return exe


def _objdump_calls(exe: Path) -> dict[str, list[tuple[int, str]]]:
    """name -> [(call address, containing function)] for direct `call <name>` instructions."""
    objdump = shutil.which("objdump")
    assert objdump, "objdump not found on PATH"
    out = subprocess.run([objdump, "-d", exe.name], capture_output=True, text=True, cwd=exe.parent).stdout
    calls: dict[str, list[tuple[int, str]]] = {}
    current = ""
    for line in out.splitlines():
        m = re.match(r"^([0-9a-f]+) <([^>]+)>:", line)
        if m:
            current = m.group(2)
            continue
        m = re.match(r"^\s+([0-9a-f]+):.*\scall\s+[0-9a-f]+ <([^>+]+)>", line)
        if m:
            calls.setdefault(m.group(2), []).append((int(m.group(1), 16), current))
    return calls


def _report(exe: Path, names: list[str], tmp: Path) -> dict:
    headless = GHIDRA / "support" / ("analyzeHeadless.bat" if os.name == "nt" else "analyzeHeadless")
    assert headless.is_file(), f"Ghidra headless not found at {headless}"
    script = ROOT / "ghidra_scripts" / "CallSiteReport.java"
    assert script.is_file(), "ghidra_scripts/CallSiteReport.java is missing"
    out = tmp / "out dir" / "report.json"  # a space in the path on purpose
    out.parent.mkdir()
    proj = tmp / "proj"
    proj.mkdir()
    p = subprocess.run([str(headless), str(proj), "hidden", "-import", str(exe), "-overwrite",
                        "-scriptPath", str(script.parent), "-postScript", script.name, str(out), *names,
                        "-deleteProject"], capture_output=True, text=True, timeout=900)
    assert out.is_file(), "no report written\n" + p.stdout[-3000:] + p.stderr[-3000:]
    return json.loads(out.read_text(encoding="utf-8"))


def _sites(entries) -> list[tuple[int, str]]:
    return [(int(str(e["address"]).lower().removeprefix("0x"), 16), e["caller"]) for e in entries]


def test_report_matches_call_instructions(tmp_path: Path):
    exe = _build(tmp_path)
    truth = _objdump_calls(exe)
    names = ["decrypt_block", "getenv", "not_in_binary"]
    report = _report(exe, names, tmp_path)

    assert set(report) == set(names), report.keys()
    assert report["not_in_binary"] == []

    got = _sites(report["decrypt_block"])
    want = sorted(truth["decrypt_block"])
    assert [a for a, _ in got] == sorted(a for a, _ in got), "entries are not sorted by address"
    # Exactly the direct calls: repeated calls each count, the function-pointer table does not.
    assert got == want, f"decrypt_block: got {got}, want {want}"
    assert sorted(c for _, c in got) == ["read_config", "stream", "stream"]

    # Imported function: the calls into its import thunk, from read_config and main.
    got_env = _sites(report["getenv"])
    want_env = sorted(truth["getenv"])
    assert got_env == want_env, f"getenv: got {got_env}, want {want_env}"
    assert sorted(c for _, c in got_env) == ["main", "read_config"]
