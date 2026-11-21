"""
Summarize an A/B folder written by run_ab.ps1: pass counts per task and arm, plus how the
coder worked (rounds, failed calls, how often each host check fired).

    python ab_summary.py <out dir> [arm prefix ...]      # default arms: on off

Reads <out>/<arm><n>.log (the PASS/FAIL lines and each task's "process" JSON).
Identical code has scored 1/5 to 5/5 on single cycles: read the per-task columns, not one run.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_RESULT_RE = re.compile(r"^(PASS|FAIL) (\S+)\s*$")
_PROCESS_RE = re.compile(r"^\s*\[(?:ok|x)\] process: (\{.*\})\s*$")


def parse_log(path: Path) -> dict[str, dict]:
    """task id -> {"passed": bool, "process": {...}}"""
    tasks: dict[str, dict] = {}
    current = None
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except PermissionError:  # the cycle that is still running holds its log open
        return {}
    for line in text.splitlines():
        m = _RESULT_RE.match(line)
        if m:
            current = m.group(2)
            tasks[current] = {"passed": m.group(1) == "PASS", "process": {}}
            continue
        m = _PROCESS_RE.match(line)
        if m and current:
            try:
                tasks[current]["process"] = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    return tasks


def summarize(out_dir: Path, arms: list[str]) -> str:
    runs: dict[str, list[dict[str, dict]]] = {}
    for arm in arms:
        logs = sorted(p for p in out_dir.glob(f"{arm}*.log") if re.fullmatch(rf"{re.escape(arm)}\d+", p.stem))
        runs[arm] = [r for r in (parse_log(p) for p in logs) if r]
    task_ids = sorted({t for cycles in runs.values() for c in cycles for t in c})
    if not task_ids:
        return f"No results under {out_dir} for arms {arms}"

    width = max(len(t) for t in task_ids + ["TOTAL"]) + 2
    lines = ["task".ljust(width) + "".join(a.ljust(12) for a in arms)]
    totals = defaultdict(lambda: [0, 0])
    for task in task_ids:
        row = task.ljust(width)
        for arm in arms:
            results = [c[task]["passed"] for c in runs[arm] if task in c]
            totals[arm][0] += sum(results)
            totals[arm][1] += len(results)
            row += f"{sum(results)}/{len(results)}".ljust(12)
        lines.append(row)
    lines.append("TOTAL".ljust(width) + "".join(f"{totals[a][0]}/{totals[a][1]}".ljust(12) for a in arms))
    lines.append("per cycle".ljust(width) + "".join(
        ",".join(str(sum(t["passed"] for t in c.values())) for c in runs[a]).ljust(12) for a in arms))

    lines.append("")
    lines.append("how it worked (mean per task run)".ljust(width + 12))
    for key in ("rounds", "elapsed_sec", "call_failures", "test_failures"):
        row = key.ljust(width)
        for arm in arms:
            values = [t["process"].get(key) for c in runs[arm] for t in c.values()]
            values = [v for v in values if isinstance(v, (int, float))]
            row += (f"{sum(values) / len(values):.1f}" if values else "-").ljust(12)
        lines.append(row)
    notes = sorted({k for a in arms for c in runs[a] for t in c.values()
                    for k in (t["process"].get("host_notes") or {})})
    if notes:
        lines.append("")
        lines.append("host notes shown (total)")
        for key in notes:
            lines.append(key.ljust(width) + "".join(
                str(sum((t["process"].get("host_notes") or {}).get(key, 0)
                        for c in runs[a] for t in c.values())).ljust(12) for a in arms))
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(summarize(Path(sys.argv[1]), sys.argv[2:] or ["on", "off"]))
