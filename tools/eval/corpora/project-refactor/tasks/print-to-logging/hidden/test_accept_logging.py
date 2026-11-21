import ast
import logging
import pathlib

from syncer import run_sync
from syncer.cli import main
from syncer.store import Store


def _records(caplog, level):
    return [(r.name, r.getMessage()) for r in caplog.records if r.levelno == level]


def test_no_prints_left_except_cli_summary():
    prints = {}
    for path in pathlib.Path("syncer").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        n = sum(
            1 for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"
        )
        if n:
            prints[path.name] = n
    assert prints == {"cli.py": 1}


def test_info_messages_and_logger_names(caplog):
    caplog.set_level(logging.DEBUG)
    run_sync("orders")
    info = _records(caplog, logging.INFO)
    assert ("syncer.pipeline", "sync start: orders") in info
    assert ("syncer.fetch", "fetching orders") in info
    assert ("syncer.transform", "transformed 2 of 3 rows") in info
    assert ("syncer.store", "saved 2 rows") in info
    assert ("syncer.pipeline", "sync done: orders") in info


def test_warnings_lose_their_prefix(caplog):
    caplog.set_level(logging.DEBUG)
    store = Store()
    run_sync("orders", store)
    run_sync("orders", store)
    run_sync("empty")
    warnings = _records(caplog, logging.WARNING)
    assert ("syncer.transform", "skipping row 2: bad amount 'oops'") in warnings
    assert ("syncer.store", "overwriting row 1") in warnings
    assert ("syncer.fetch", "source empty is empty") in warnings
    assert not any("WARNING" in msg for _, msg in warnings)


def test_errors_are_logged_and_cli_output_is_only_the_summary(caplog, capsys):
    caplog.set_level(logging.DEBUG)
    assert main(["nope"]) == 1
    errors = _records(caplog, logging.ERROR)
    assert ("syncer.fetch", "unknown source nope") in errors
    assert ("syncer.cli", "sync failed") in errors
    assert capsys.readouterr().out == ""
    assert main(["orders"]) == 0
    assert capsys.readouterr().out == "2 rows synced from orders\n"


def test_package_modules_do_not_configure_logging():
    for path in pathlib.Path("syncer").glob("*.py"):
        if path.name != "cli.py":
            assert "basicConfig" not in path.read_text(encoding="utf-8"), path.name
