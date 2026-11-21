# ledger

    from ledger import Book, Entry

    book = Book()
    book.add(Entry("coffee", "3.50", "food"))
    print(book.balance())

Entries are frozen `Entry` dataclasses with the fields `description`, `amount` and `category`.
