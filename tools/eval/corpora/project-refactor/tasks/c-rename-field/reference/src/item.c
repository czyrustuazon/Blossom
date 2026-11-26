#include <string.h>

#include "item.h"

void item_init(struct item *it, const char *name, int quantity, int price_cents)
{
    strncpy(it->name, name, ITEM_NAME_MAX - 1);
    it->name[ITEM_NAME_MAX - 1] = '\0';
    it->quantity = quantity;
    it->price_cents = price_cents;
}

long item_value_cents(const struct item *it)
{
    return (long)it->quantity * it->price_cents;
}

void item_restock(struct item *it, int units)
{
    it->quantity += units;
}

/* Removes up to `units` from stock and returns how many were actually taken. */
int item_take(struct item *it, int units)
{
    int taken = units < it->quantity ? units : it->quantity;
    it->quantity -= taken;
    return taken;
}
