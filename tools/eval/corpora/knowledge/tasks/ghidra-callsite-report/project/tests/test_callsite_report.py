"""Runs ghidra_scripts/CallSiteReport.java headless on samples/login.c (needs gcc and Ghidra)."""
from pathlib import Path

from headless import ROOT, call_site_report


def test_checksum_callers(tmp_path: Path):
    report = call_site_report(ROOT / "samples" / "login.c", ["checksum"], tmp_path)
    assert list(report) == ["checksum"]
    sites = report["checksum"]
    assert sorted(s["caller"] for s in sites) == ["handle_login", "handle_logout", "handle_logout"]
    addresses = [int(s["address"], 16) for s in sites]
    assert addresses == sorted(addresses)


def test_unknown_name_is_empty(tmp_path: Path):
    report = call_site_report(ROOT / "samples" / "login.c", ["no_such_function"], tmp_path)
    assert report == {"no_such_function": []}
