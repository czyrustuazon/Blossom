# invkit

A tiny C11 inventory library.

## Data model

- `struct item` — `name`, `quantity` (units on hand), `price_cents`. `ITEM_IS_EMPTY(it)` is true when
  `it->quantity` is 0.
- `struct inventory` — up to 16 items; adding an existing name adds to its `quantity`.
- `struct order_line` — `item_name` and `qty` (units the customer ordered). `order_fulfill` takes
  stock for each line and returns the units it could not fill.

## CSV report

`report_csv` writes a header `name,quantity,price_cents` and one line per item. The importer finds
integer columns with `report_field_offset("quantity")` / `report_field_offset("price_cents")`.

## Tests

```
python -m pytest tests
```

The tests build `src/*.c` with `tests/driver.c` using gcc (`-Wall -Wextra -Werror`).
