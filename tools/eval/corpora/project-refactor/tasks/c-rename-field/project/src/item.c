#include <string.h>

#include "item.h"

void item_init(struct item *it, const char *name, int qty, int price_cents)
{
    strncpy(it->name, name, ITEM_NAME_MAX - 1);
    it->name[ITEM_NAME_MAX - 1] = '\0';
    it->qty = qty;
    it->price_cents = price_cents;
}

long item_value_cents(const struct item *it)
{
    return (long)it->qty * it->price_cents;
}

void item_restock(struct item *it, int units)
{
    it->qty += units;
}

/* Removes up to `units` from stock and returns how many were actually taken. */
int item_take(struct item *it, int units)
{
    int taken = units < it->qty ? units : it->qty;
    it->qty -= taken;
    return taken;
}
