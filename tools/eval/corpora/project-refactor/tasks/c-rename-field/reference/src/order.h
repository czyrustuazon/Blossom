#ifndef INVKIT_ORDER_H
#define INVKIT_ORDER_H

#include "inventory.h"

/* A customer's request for some units of one item. */
struct order_line {
    char item_name[ITEM_NAME_MAX];
    int qty;  /* units ordered */
};

/* Takes stock for each line; returns the number of units that could not be filled. */
int order_fulfill(struct inventory *inv, const struct order_line *lines, int n_lines);

#endif
