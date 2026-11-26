#ifndef INVKIT_INVENTORY_H
#define INVKIT_INVENTORY_H

#include "item.h"

#define INVENTORY_MAX 16

struct inventory {
    struct item items[INVENTORY_MAX];
    int count;
};

void inventory_init(struct inventory *inv);
struct item *inventory_add(struct inventory *inv, const char *name, int qty, int price_cents);
struct item *inventory_find(struct inventory *inv, const char *name);
long inventory_total_units(const struct inventory *inv);
long inventory_value_cents(const struct inventory *inv);
int inventory_empty_count(const struct inventory *inv);

#endif
