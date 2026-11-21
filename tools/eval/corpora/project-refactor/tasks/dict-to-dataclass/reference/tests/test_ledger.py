from decimal import Decimal

import pytest

from ledger import Book, Entry, by_category, largest, to_rows


def _book():
    book = Book()
    book.add(Entry("coffee", "3.50", "food"))
    book.add(Entry("salary", 1200, "income"))
    book.add(Entry("lunch", "-12.25", "food"))
    book.add(Entry("stamps", "2"))
    return book


def test_entry_normalizes_amount():
    entry = Entry("coffee", "3.50", "food")
    assert entry.amount == Decimal("3.50")
    assert entry.category == "food"
    assert Entry("stamps", 2).category == "misc"


def test_empty_description_rejected():
    with pytest.raises(ValueError):
        Entry("", 1)


def test_balance_and_lookup():
    book = _book()
    assert book.balance() == Decimal("1193.25")
    assert [e.description for e in book.find("LUN")] == ["lunch"]
    assert [e.description for e in book.in_category("food")] == ["coffee", "lunch"]


def test_zero_amount_rejected():
    with pytest.raises(ValueError):
        Book().add(Entry("nothing", 0))


def test_reports():
    book = _book()
    assert by_category(book.entries) == {
        "food": Decimal("-8.75"), "income": Decimal("1200"), "misc": Decimal("2"),
    }
    assert [e.description for e in largest(book.entries, 2)] == ["salary", "lunch"]


def test_export_rows():
    assert to_rows(_book().entries)[:2] == [
        ["description", "amount", "category"],
        ["coffee", "3.50", "food"],
    ]
