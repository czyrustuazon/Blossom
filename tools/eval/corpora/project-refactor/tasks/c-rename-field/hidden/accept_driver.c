/* Hidden acceptance driver: only compiles if struct item has `quantity` (and no `qty`) while
 * struct order_line keeps `qty`. */
#include <stdio.h>

#include "inventory.h"
#include "order.h"
#include "report.h"

int main(void)
{
    struct item it = { .name = "cog", .quantity = 4, .price_cents = 250 };
    struct order_line line = { .item_name = "cog", .qty = 3 };

    struct inventory inv;
    inventory_init(&inv);
    struct item *cog = inventory_add(&inv, it.name, it.quantity, it.price_cents);
    printf("empty_before %d\n", ITEM_IS_EMPTY(cog));
    printf("short %d\n", order_fulfill(&inv, &line, 1));
    printf("left %d\n", cog->quantity);
    printf("take %d\n", item_take(cog, 5));
    printf("empty_after %d\n", ITEM_IS_EMPTY(cog));
    printf("value %ld\n", item_value_cents(&it));

    long off = report_field_offset("quantity");
    printf("offset_ok %d\n", off >= 0 && *(int *)((char *)&it + off) == 4);
    printf("old_column %ld\n", report_field_offset("qty"));
    report_csv(stdout, &inv);
    return 0;
}
