import pytest

from syncer import run_sync
from syncer.cli import main
from syncer.store import Store


def test_sync_orders_skips_bad_row():
    saved, store = run_sync("orders")
    assert saved == 2
    assert store.rows == {1: 1050, 3: 425}


def test_sync_empty_source():
    saved, store = run_sync("empty")
    assert saved == 0 and store.rows == {}


def test_unknown_source_raises():
    with pytest.raises(KeyError):
        run_sync("nope")


def test_resync_overwrites():
    store = Store()
    run_sync("orders", store)
    saved, _ = run_sync("orders", store)
    assert saved == 2


def test_cli_prints_summary(capsys):
    assert main(["orders"]) == 0
    assert "2 rows synced from orders" in capsys.readouterr().out
