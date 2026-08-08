from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .corpus import CheckSpec, TaskSpec


@dataclass
class CheckResult:
    check_id: str
    passed: bool
    detail: str


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _compare(haystack: str, needle: str, case_insensitive: bool) -> bool:
    if case_insensitive:
        return needle.lower() in haystack.lower()
    return needle in haystack


def run_check(
    check: CheckSpec,
    *,
    work_dir: Path,
    response_text: str,
    timeout_sec: int = 120,
) -> CheckResult:
    ctype = check.type.lower()

    if ctype in {"response_contains", "response_regex"}:
        text = response_text or ""
        if ctype == "response_regex":
            flags = re.IGNORECASE if check.case_insensitive else 0
            ok = bool(re.search(check.pattern or check.value, text, flags))
            detail = f"response matches /{check.pattern or check.value}/" if ok else "no regex match in response"
        else:
            ok = _compare(text, check.value or check.pattern, check.case_insensitive)
            detail = f"response contains {check.value!r}" if ok else f"response missing {check.value!r}"
        return CheckResult(check.id, ok, detail)

    if ctype == "manual":
        return CheckResult(check.id, False, "manual check — review required")

    target = work_dir / check.path.replace("\\", "/") if check.path else None
    if ctype in {"contains", "not_contains", "regex"} and not target:
        return CheckResult(check.id, False, "check missing path")

    if ctype == "contains":
        if not target or not target.is_file():
            return CheckResult(check.id, False, f"missing file {check.path}")
        ok = _compare(_read_text(target), check.value, check.case_insensitive)
        return CheckResult(
            check.id,
            ok,
            f"{check.path} contains {check.value!r}" if ok else f"{check.path} missing {check.value!r}",
        )

    if ctype == "not_contains":
        if not target or not target.is_file():
            return CheckResult(check.id, False, f"missing file {check.path}")
        ok = not _compare(_read_text(target), check.value, check.case_insensitive)
        return CheckResult(
            check.id,
            ok,
            f"{check.path} excludes {check.value!r}" if ok else f"{check.path} still contains {check.value!r}",
        )

    if ctype == "regex":
        if not target or not target.is_file():
            return CheckResult(check.id, False, f"missing file {check.path}")
        flags = re.IGNORECASE if check.case_insensitive else 0
        ok = bool(re.search(check.pattern or check.value, _read_text(target), flags))
        return CheckResult(
            check.id,
            ok,
            f"{check.path} matches /{check.pattern or check.value}/" if ok else "regex not found",
        )

    if ctype == "command":
        cmd = check.command or check.value
        if not cmd:
            return CheckResult(check.id, False, "empty command")
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            return CheckResult(check.id, False, f"timeout: {cmd}")
        except OSError as exc:
            return CheckResult(check.id, False, f"command failed to start: {exc}")

        ok = proc.returncode == check.expect_exit
        detail = f"exit {proc.returncode} (expected {check.expect_exit})"
        if check.stdout_pattern:
            flags = re.IGNORECASE if check.case_insensitive else 0
            if not re.search(check.stdout_pattern, proc.stdout or "", flags):
                ok = False
                detail += f"; stdout missing /{check.stdout_pattern}/"
        if not ok and proc.stderr.strip():
            detail += f"; stderr: {proc.stderr.strip()[:200]}"
        return CheckResult(check.id, ok, detail)

    return CheckResult(check.id, False, f"unknown check type {check.type!r}")


def score_task(
    task: TaskSpec,
    *,
    work_dir: Path,
    response_text: str,
) -> tuple[bool, list[CheckResult]]:
    results = [
        run_check(check, work_dir=work_dir, response_text=response_text)
        for check in task.checks
    ]
    passed = bool(results) and all(r.passed for r in results)
    return passed, results
