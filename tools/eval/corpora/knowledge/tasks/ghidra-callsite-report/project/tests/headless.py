"""Builds a sample C program with gcc and runs a script from ghidra_scripts/ on it with Ghidra headless."""
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GHIDRA = Path(r"C:\Program Files\ghidra_12.1.2")


def ghidra_headless() -> Path:
    home = Path(os.environ.get("GHIDRA_INSTALL_DIR") or DEFAULT_GHIDRA)
    exe = home / "support" / ("analyzeHeadless.bat" if os.name == "nt" else "analyzeHeadless")
    if not exe.is_file():
        raise RuntimeError(f"Ghidra headless not found at {exe} (set GHIDRA_INSTALL_DIR)")
    return exe


def build_sample(source: Path, out_dir: Path) -> Path:
    gcc = shutil.which("gcc")
    if not gcc:
        raise RuntimeError("gcc not found on PATH")
    exe = out_dir / (source.stem + ".exe")
    build = subprocess.run([gcc, "-O1", "-o", exe.as_posix(), source.name],
                           capture_output=True, text=True, cwd=source.parent)
    if build.returncode != 0:
        raise RuntimeError(build.stderr)
    return exe


def run_script(binary: Path, script: str, args: list[str], work: Path) -> subprocess.CompletedProcess:
    proj = work / "ghidra_project"
    proj.mkdir(parents=True, exist_ok=True)
    cmd = [str(ghidra_headless()), str(proj), "sample", "-import", str(binary), "-overwrite",
           "-scriptPath", str(ROOT / "ghidra_scripts"), "-postScript", script, *args, "-deleteProject"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=900)


def call_site_report(source: Path, names: list[str], work: Path) -> dict:
    """Runs CallSiteReport.java on the compiled source and returns its JSON."""
    binary = build_sample(source, work)
    out = work / "report.json"
    proc = run_script(binary, "CallSiteReport.java", [str(out), *names], work)
    if not out.is_file():
        raise AssertionError("CallSiteReport.java wrote no report.\n" + proc.stdout[-4000:] + proc.stderr[-4000:])
    return json.loads(out.read_text(encoding="utf-8"))
