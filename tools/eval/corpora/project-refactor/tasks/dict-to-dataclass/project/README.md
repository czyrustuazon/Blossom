# ledger

    from ledger import Book, make_entry

    book = Book()
    book.add(make_entry("coffee", "3.50", "food"))
    print(book.balance())

Entries are dicts with the keys `description`, `amount` and `category`.
