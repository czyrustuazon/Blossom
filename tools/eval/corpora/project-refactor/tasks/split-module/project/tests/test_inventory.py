import pytest

from inventory import Item, Store, format_report, main, restock_list


def test_store_roundtrip(tmp_path):
    db = tmp_path / "inv.json"
    s = Store(db)
    s.add(Item("A1", "Widget", 3, 2.5))
    s.save()
    again = Store(db)
    assert again.items["A1"].value == 7.5
    with pytest.raises(ValueError):
        again.adjust("A1", -4)


def test_report_and_restock():
    items = [Item("B2", "Bolt", 10, 0.1), Item("A1", "Widget", 3, 2.5)]
    report = format_report(items)
    assert report.splitlines()[1].startswith("A1")
    assert report.splitlines()[1].endswith(" !")
    assert restock_list(items) == ["A1"]


def test_cli(tmp_path, capsys):
    db = str(tmp_path / "x.json")
    assert main(["--db", db, "add", "C3", "Cog", "--qty", "7", "--cost", "1"]) == 0
    assert main(["--db", db, "report"]) == 0
    assert "C3" in capsys.readouterr().out
