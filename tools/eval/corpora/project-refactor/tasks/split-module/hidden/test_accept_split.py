import pathlib
import subprocess
import sys

import inventory
from inventory import Item, Store, format_report, main, restock_list
from inventory.models import Item as MItem
from inventory.storage import Store as SStore
from inventory.reports import format_report as RFormat, restock_list as RRestock
from inventory.cli import main as CMain


def test_layout():
    assert pathlib.Path("inventory").is_dir()
    assert not pathlib.Path("inventory.py").exists(), "old single-file module must be removed"
    assert Item is MItem and Store is SStore and format_report is RFormat
    assert restock_list is RRestock and main is CMain


def test_each_concern_lives_in_its_module():
    src = {p.name: p.read_text(encoding="utf-8") for p in pathlib.Path("inventory").glob("*.py")}
    assert "class Item" in src["models.py"]
    assert "class Store" in src["storage.py"] and "class Item" not in src["storage.py"]
    assert "def format_report" in src["reports.py"]
    assert "argparse" in src["cli.py"] and "argparse" not in src.get("__init__.py", "")


def test_python_dash_m_still_works(tmp_path):
    db = tmp_path / "db.json"
    run = lambda *a: subprocess.run([sys.executable, "-m", "inventory", "--db", str(db), *a],
                                    capture_output=True, text=True, cwd=pathlib.Path.cwd())
    assert run("add", "Z9", "Gear", "--qty", "2", "--cost", "3").returncode == 0
    out = run("report")
    assert out.returncode == 0, out.stderr
    assert "Z9" in out.stdout and "6.00" in out.stdout
