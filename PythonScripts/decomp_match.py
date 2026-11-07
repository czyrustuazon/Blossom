"""Local drafts for one slice of a binary. Never calls a paid model.

Two backends:

  binary     Any native slice you name. Capstone disassembles it, the local
             coder writes a short note and C, and an optional --check command
             decides whether the draft is good. Nothing is registered for you.

  ctrdecomp  The 3DS ARMCC matching repo (nlpp-decomp). Picks a ready leaf,
             diffs with ctrdecomp, and stops before functions.toml or relink.

  python PythonScripts/decomp_match.py draft --binary path\\to\\file --arch x64 --off 1000 --size 80
  python PythonScripts/decomp_match.py draft --binary path --arch arm --off 542828 --size 40 --base 100000
  python PythonScripts/decomp_match.py draft --check "python my_check.py {src}" --binary ... 
  python PythonScripts/decomp_match.py next
  python PythonScripts/decomp_match.py draft --backend ctrdecomp

Model: BLOSSOM_DECOMP_URL. Default http://127.0.0.1:11434/v1/chat/completions
(llama-server, not ChatRouter).
ctrdecomp project: NLPP_DECOMP_ROOT, else ../nlpp-decomp.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
BLOSSOM_ROOT = SCRIPT_DIR.parent
VA_BIAS = 0x100000
DEFAULT_URL = "http://127.0.0.1:11434/v1/chat/completions"

ARCHES = ("arm", "thumb", "arm64", "x86", "x64", "mips", "mipsel")

SYSTEM_BINARY = """You recover one function from the disassembly you are given.
Reply with two fenced blocks and nothing else:
1. a text block: what it does, which constants and calls matter, and what is still unknown
2. a C block that implements that behavior
Name the function exactly as instructed.
Do not claim the recovery is verified."""

SYSTEM_CTR = """You rewrite one 3DS ARMCC function so a later compile can match the retail bytes.
Reply with one fenced C or C++ block and nothing else.
Name the function exactly as instructed. Use the file offset, not the virtual address.
Do not claim the function matches. Do not mention functions.toml or relink.
Trailing literal pools are part of the function's size."""


def project_root(explicit: str | None = None) -> Path:
    raw = explicit or os.getenv("NLPP_DECOMP_ROOT") or str(BLOSSOM_ROOT.parent / "nlpp-decomp")
    path = Path(raw).resolve()
    if not (path / "ctrdecomp").is_dir():
        raise SystemExit(f"Not a ctrdecomp project: {path}")
    return path


def parse_ready(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        m = re.match(
            r"(?i)^([0-9a-f]{6})\s+([0-9a-f]+)\s+callees=\s*(\d+)\s+callers=\s*(\d+)\s+(\S+)",
            line.strip(),
        )
        if not m:
            continue
        off = int(m.group(1), 16)
        rows.append(
            {
                "backend": "ctrdecomp",
                "offset": off,
                "offset_hex": f"{off:06x}",
                "size": int(m.group(2), 16),
                "size_hex": m.group(2),
                "callees": int(m.group(3)),
                "callers": int(m.group(4)),
                "exidx": m.group(5),
                "va": off + VA_BIAS,
                "symbol": f"fn_{off:06x}",
                "arch": "arm",
            }
        )
    return rows


def extract_fenced(reply: str, kind: str) -> str | None:
    found = re.findall(rf"```{kind}\s*([\s\S]*?)```", reply, re.I)
    return found[-1].strip() if found else None


def extract_code(reply: str) -> str:
    for kind in (r"c\+\+", r"cpp", r"cxx", r"c"):
        block = extract_fenced(reply, kind)
        if block:
            return block + "\n"
    any_block = re.findall(r"```\s*([\s\S]*?)```", reply)
    if any_block:
        return any_block[-1].strip() + "\n"
    return reply.strip() + "\n"


def build_messages(fn: dict, asm: str, previous: str | None, diff: str | None, attempt: int) -> list[dict]:
    if fn.get("backend") == "ctrdecomp":
        flags = "--exceptions" if "inline" in fn["exidx"] or "extab" in fn["exidx"] else "plain (no --exceptions)"
        system = SYSTEM_CTR
        body = (
            f"Attempt {attempt}.\n"
            f"File offset 0x{fn['offset_hex']}. VA 0x{fn['va']:08x} (offset + 0x100000).\n"
            f"Size 0x{fn['size_hex']} bytes including the literal pool.\n"
            f"exidx kind {fn['exidx']}. Compile flags to assume: {flags}.\n"
            f"Define a function named exactly {fn['symbol']}.\n\n"
            f"Retail disassembly at the file offset:\n{asm.strip()}\n"
        )
    else:
        system = SYSTEM_BINARY
        body = (
            f"Attempt {attempt}.\n"
            f"Architecture {fn.get('arch', 'unknown')}.\n"
            f"File offset 0x{fn['offset_hex']}. Address 0x{fn['va']:x}.\n"
            f"Slice length 0x{fn['size_hex']} bytes.\n"
            f"Image: {fn.get('image', '')}\n"
            f"Define a function named exactly {fn['symbol']}.\n\n"
            f"Disassembly:\n{asm.strip()}\n"
        )
    if previous and diff:
        body += f"\nPrevious draft failed the check:\n{diff.strip()}\n\nPrevious source:\n{previous.strip()}\n"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": body},
    ]


def parse_score(diff_text: str) -> int | None:
    m = re.search(r"score\s+(\d+)\b", diff_text)
    return int(m.group(1)) if m else None


def next_action(score: int | None, attempt: int, max_attempts: int, *, checked: bool | None = None) -> str:
    if checked is True or score == 0:
        return "pending_relink" if score == 0 and checked is None else "checked"
    if checked is None and score is None:
        return "unverified"
    if attempt >= max_attempts:
        return "human"
    return "retry"


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def ready_functions(project: Path, top: int) -> list[dict]:
    proc = _run(
        [sys.executable, "tools/handmatch/ready.py", "--int", "--top", str(top)],
        project,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or proc.stdout.strip() or "ready.py failed")
    rows = parse_ready(proc.stdout)
    if not rows:
        raise SystemExit("ready.py returned no integer-only leaves")
    return rows


def disassemble_ctr(project: Path, fn: dict) -> str:
    proc = _run(
        [sys.executable, "tools/handmatch/rdis.py", fn["offset_hex"], fn["size_hex"]],
        project,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "rdis.py failed")
    return proc.stdout


def disassemble_bytes(blob: bytes, arch: str, address: int) -> str:
    import capstone

    table = {
        "arm": (capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM),
        "thumb": (capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB),
        "arm64": (capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM),
        "x86": (capstone.CS_ARCH_X86, capstone.CS_MODE_32),
        "x64": (capstone.CS_ARCH_X86, capstone.CS_MODE_64),
        "mips": (capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_BIG_ENDIAN),
        "mipsel": (capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN),
    }
    if arch not in table:
        raise SystemExit(f"Unknown arch {arch}. Choose from: {', '.join(ARCHES)}")
    md = capstone.Cs(*table[arch])
    md.skipdata = True
    lines = [f"{ins.address:08x}: {ins.mnemonic} {ins.op_str}".rstrip() for ins in md.disasm(blob, address)]
    if not lines:
        raise SystemExit(f"Capstone produced no instructions for arch {arch} at 0x{address:x}")
    return "\n".join(lines) + "\n"


def disassemble_binary(path: Path, fn: dict) -> str:
    data = path.read_bytes()
    off, size = fn["offset"], fn["size"]
    if off < 0 or size <= 0 or off + size > len(data):
        raise SystemExit(f"Slice 0x{off:x}+0x{size:x} is outside {path} ({len(data)} bytes)")
    return disassemble_bytes(data[off : off + size], fn["arch"], fn["va"])


def complete(url: str, messages: list[dict], timeout: float) -> str:
    response = requests.post(
        url,
        json={"messages": messages, "temperature": 0.2, "stream": False},
        timeout=timeout,
    )
    response.raise_for_status()
    message = response.json()["choices"][0]["message"]
    return (message.get("content") or message.get("reasoning_content") or "").strip()


def diff_draft(project: Path, src: Path, fn: dict) -> str:
    cmd = [
        sys.executable,
        "-m",
        "ctrdecomp",
        "diff",
        str(src),
        fn["symbol"],
        fn["offset_hex"],
        fn["size_hex"],
    ]
    if "inline" in fn["exidx"] or "extab" in fn["exidx"]:
        cmd.extend(["--", "--exceptions"])
    proc = _run(cmd, project)
    return (proc.stdout or "") + (proc.stderr or "")


def run_check(template: str, src: Path, cwd: Path) -> tuple[bool, str]:
    if "{src}" not in template:
        raise SystemExit("--check must include {src}")
    cmd = shlex.split(template.format(src=str(src)), posix=False)
    proc = _run(cmd, cwd)
    text = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, text


def draft_loop(
    fn: dict,
    asm: str,
    src: Path,
    *,
    url: str,
    attempts: int,
    timeout: float,
    verify,
) -> dict:
    previous = None
    diff_text = None
    score = None
    checked = None
    action = "human"
    for attempt in range(1, attempts + 1):
        reply = complete(url, build_messages(fn, asm, previous, diff_text, attempt), timeout)
        note = extract_fenced(reply, "text")
        code = extract_code(reply)
        if fn["symbol"] not in code:
            code = f"/* model omitted the required name */\n{code}"
        if note:
            commented = "\n".join(f"// {line}" if line else "//" for line in note.splitlines())
            code = commented + "\n" + code
        src.write_text(code, encoding="utf-8")
        score, checked, diff_text = verify(src)
        action = next_action(score, attempt, attempts, checked=checked)
        previous = code
        if action != "retry":
            break
    return {
        "backend": fn.get("backend", "binary"),
        "arch": fn.get("arch"),
        "offset": fn["offset_hex"],
        "symbol": fn["symbol"],
        "draft": str(src),
        "score": score,
        "action": action,
        "diff": diff_text or "",
    }


def draft_ctr(project: Path, fn: dict, *, url: str, attempts: int, timeout: float) -> dict:
    asm = disassemble_ctr(project, fn)
    drafts = project / "handoff_drafts"
    drafts.mkdir(exist_ok=True)
    src = drafts / f"blossom_{fn['offset_hex']}.cpp"

    def verify(path: Path):
        text = diff_draft(project, path, fn)
        return parse_score(text), None, text

    return draft_loop(fn, asm, src, url=url, attempts=attempts, timeout=timeout, verify=verify)


def draft_binary(
    image: Path,
    fn: dict,
    *,
    url: str,
    attempts: int,
    timeout: float,
    out: Path,
    check: str | None,
) -> dict:
    asm = disassemble_binary(image, fn)
    out.mkdir(parents=True, exist_ok=True)
    src = out / f"blossom_{fn['arch']}_{fn['offset_hex']}.c"

    def verify(path: Path):
        if not check:
            return None, None, ""
        ok, text = run_check(check, path, out)
        return None, ok, text

    return draft_loop(fn, asm, src, url=url, attempts=attempts, timeout=timeout, verify=verify)


def _hex(text: str) -> int:
    return int(text, 16)


def _binary_fn(args) -> dict:
    off = _hex(args.off)
    size = _hex(args.size)
    base = _hex(args.base) if args.base else 0
    return {
        "backend": "binary",
        "offset": off,
        "offset_hex": f"{off:x}",
        "size": size,
        "size_hex": f"{size:x}",
        "va": base + off,
        "symbol": f"fn_{off:x}",
        "arch": args.arch,
        "image": str(Path(args.binary).resolve()),
    }


def _print_result(result: dict) -> int:
    shown = dict(result)
    shown["diff"] = "\n".join((result["diff"] or "").splitlines()[-40:])
    print(json.dumps(shown, indent=2))
    if result["action"] == "pending_relink":
        print(
            "Score 0 on this draft only. It is not registered. "
            "Relink yourself when no other relink is running, then append functions.toml.",
            file=sys.stderr,
        )
    if result["action"] == "unverified":
        print("No checker ran. The draft is a reading of the slice, not a match.", file=sys.stderr)
    return 0 if result["action"] in ("pending_relink", "checked", "unverified") else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Local decomp drafts for one binary slice")
    sub = ap.add_subparsers(dest="cmd", required=True)

    nxt = sub.add_parser("next", help="Next ready leaf in a ctrdecomp project")
    nxt.add_argument("--project", help="ctrdecomp repo (default NLPP_DECOMP_ROOT or ../nlpp-decomp)")
    nxt.add_argument("--top", type=int, default=5)

    dr = sub.add_parser("draft", help="Ask the local model for one slice")
    dr.add_argument("--backend", choices=("binary", "ctrdecomp"), default="binary")
    dr.add_argument("--binary", help="File to slice (binary backend)")
    dr.add_argument("--arch", choices=ARCHES, help="Instruction set (binary backend)")
    dr.add_argument("--base", help="Address of file byte 0, hex. Default 0 (addresses are file offsets)")
    dr.add_argument("--off", help="File offset hex")
    dr.add_argument("--size", help="Slice length hex")
    dr.add_argument("--check", help="Command run on the draft; include {src}. Exit 0 accepts it")
    dr.add_argument("--out", help="Draft directory (default handoff_drafts under Blossom)")
    dr.add_argument("--project", help="ctrdecomp repo")
    dr.add_argument("--exidx", default="cantunwind", help="ctrdecomp exidx kind when --off is set")
    dr.add_argument("--attempts", type=int, default=3)
    dr.add_argument("--timeout", type=float, default=300.0)
    dr.add_argument("--url", default=os.getenv("BLOSSOM_DECOMP_URL", DEFAULT_URL))

    args = ap.parse_args(argv)
    if args.cmd == "next":
        print(json.dumps(ready_functions(project_root(args.project), args.top), indent=2))
        return 0

    if args.backend == "ctrdecomp":
        project = project_root(args.project)
        if args.off:
            if not args.size:
                raise SystemExit("--size is required with --off")
            off = _hex(args.off)
            fn = {
                "backend": "ctrdecomp",
                "offset": off,
                "offset_hex": f"{off:06x}",
                "size": _hex(args.size),
                "size_hex": args.size.lower().removeprefix("0x"),
                "exidx": args.exidx,
                "va": off + VA_BIAS,
                "symbol": f"fn_{off:06x}",
                "arch": "arm",
            }
        else:
            fn = ready_functions(project, 1)[0]
        result = draft_ctr(project, fn, url=args.url, attempts=args.attempts, timeout=args.timeout)
        return _print_result(result)

    if not args.binary or not args.arch or not args.off or not args.size:
        raise SystemExit("binary backend needs --binary, --arch, --off, and --size")
    image = Path(args.binary).resolve()
    if not image.is_file():
        raise SystemExit(f"No such file: {image}")
    out = Path(args.out).resolve() if args.out else BLOSSOM_ROOT / "handoff_drafts"
    result = draft_binary(
        image,
        _binary_fn(args),
        url=args.url,
        attempts=args.attempts,
        timeout=args.timeout,
        out=out,
        check=args.check,
    )
    return _print_result(result)


if __name__ == "__main__":
    raise SystemExit(main())
