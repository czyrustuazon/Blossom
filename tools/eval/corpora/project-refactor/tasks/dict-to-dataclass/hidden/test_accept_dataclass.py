import dataclasses
import pathlib
import re
from decimal import Decimal

import pytest

import ledger
from ledger import Book, Entry, by_category, largest, to_rows
from ledger import models


def test_entry_is_a_frozen_dataclass():
    assert dataclasses.is_dataclass(Entry)
    assert [f.name for f in dataclasses.fields(Entry)] == ["description", "amount", "category"]
    entry = Entry("coffee", "3.50", "food")
    assert entry.amount == Decimal("3.50") and isinstance(entry.amount, Decimal)
    assert Entry("stamps", 2).category == "misc"
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.amount = Decimal("1")
    with pytest.raises(ValueError):
        Entry("", 1)


def test_make_entry_is_gone():
    assert not hasattr(ledger, "make_entry") and not hasattr(models, "make_entry")
    assert "Entry" in ledger.__all__ and "make_entry" not in ledger.__all__
    offenders = [
        str(p) for p in pathlib.Path("ledger").glob("*.py")
        if "make_entry" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_no_dict_subscripts_left_in_package():
    pattern = re.compile(r"\[\s*[\"'](description|amount|category)[\"']\s*\]")
    offenders = [
        str(p) for p in pathlib.Path("ledger").glob("*.py") if pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_behavior_preserved_with_entries():
    book = Book()
    book.add(Entry("coffee", "3.50", "food"))
    book.add(Entry("salary", 1200, "income"))
    book.add(Entry("lunch", "-12.25", "food"))
    assert book.balance() == Decimal("1191.25")
    assert book.find("cof") == [Entry("coffee", "3.50", "food")]
    assert [e.description for e in book.in_category("food")] == ["coffee", "lunch"]
    assert by_category(book.entries) == {"food": Decimal("-8.75"), "income": Decimal("1200")}
    assert largest(book.entries)[0].description == "salary"
    assert to_rows(book.entries)[3] == ["lunch", "-12.25", "food"]
    with pytest.raises(ValueError):
        book.add(Entry("nothing", 0))
