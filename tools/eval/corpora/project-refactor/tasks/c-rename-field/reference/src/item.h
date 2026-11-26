#ifndef INVKIT_ITEM_H
#define INVKIT_ITEM_H

#define ITEM_NAME_MAX 32

/* One stock-keeping unit held in the inventory. */
struct item {
    char name[ITEM_NAME_MAX];
    int quantity;     /* units on hand */
    int price_cents;  /* unit price */
};

#define ITEM_IS_EMPTY(it) ((it)->quantity == 0)

void item_init(struct item *it, const char *name, int quantity, int price_cents);
long item_value_cents(const struct item *it);
void item_restock(struct item *it, int units);
int item_take(struct item *it, int units);

#endif
