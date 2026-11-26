#include <string.h>

#include "inventory.h"

void inventory_init(struct inventory *inv)
{
    inv->count = 0;
}

struct item *inventory_add(struct inventory *inv, const char *name, int qty, int price_cents)
{
    struct item *existing = inventory_find(inv, name);
    if (existing) {
        existing->qty += qty;
        return existing;
    }
    if (inv->count >= INVENTORY_MAX)
        return NULL;
    inv->items[inv->count] = (struct item){ .qty = qty, .price_cents = price_cents };
    strncpy(inv->items[inv->count].name, name, ITEM_NAME_MAX - 1);
    return &inv->items[inv->count++];
}

struct item *inventory_find(struct inventory *inv, const char *name)
{
    for (int i = 0; i < inv->count; i++)
        if (strcmp(inv->items[i].name, name) == 0)
            return &inv->items[i];
    return NULL;
}

long inventory_total_units(const struct inventory *inv)
{
    long units = 0;
    for (const struct item *it = inv->items; it < inv->items + inv->count; ++it)
        units += it->qty;
    return units;
}

long inventory_value_cents(const struct inventory *inv)
{
    long total = 0;
    for (int i = 0; i < inv->count; i++)
        total += item_value_cents(&inv->items[i]);
    return total;
}

int inventory_empty_count(const struct inventory *inv)
{
    int n = 0;
    for (int i = 0; i < inv->count; i++)
        if (ITEM_IS_EMPTY(&inv->items[i]))
            n++;
    return n;
}
