#include "order.h"

int order_fulfill(struct inventory *inv, const struct order_line *lines, int n_lines)
{
    int short_units = 0;
    for (int i = 0; i < n_lines; i++) {
        const struct order_line *line = &lines[i];
        struct item *it = inventory_find(inv, line->item_name);
        if (!it) {
            short_units += line->qty;
            continue;
        }
        if (it->qty >= line->qty) {
            it->qty -= line->qty;
        } else {
            short_units += line->qty - it->qty;
            it->qty = 0;
        }
    }
    return short_units;
}
