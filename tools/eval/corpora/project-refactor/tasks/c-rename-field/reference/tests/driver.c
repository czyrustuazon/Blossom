/* Test driver: exercises the library and prints results that test_inventory.py checks. */
#include <stdio.h>

#include "../src/inventory.h"
#include "../src/order.h"
#include "../src/report.h"

int main(void)
{
    struct inventory inv;
    inventory_init(&inv);
    inventory_add(&inv, "bolt", 100, 12);
    inventory_add(&inv, "nut", 40, 5);
    struct item *washer = inventory_add(&inv, "washer", 0, 2);
    inventory_add(&inv, "nut", 10, 5);

    printf("units %ld\n", inventory_total_units(&inv));
    printf("value %ld\n", inventory_value_cents(&inv));
    printf("empty %d\n", inventory_empty_count(&inv));
    printf("washer %d\n", washer->quantity);

    item_restock(washer, 7);
    printf("washer_restocked %d\n", washer->quantity);

    struct order_line lines[] = {
        { .item_name = "bolt", .qty = 30 },
        { .item_name = "nut", .qty = 60 },
        { .item_name = "gear", .qty = 3 },
    };
    printf("short %d\n", order_fulfill(&inv, lines, 3));
    printf("bolt_left %d\n", inventory_find(&inv, "bolt")->quantity);
    printf("nut_left %d\n", inventory_find(&inv, "nut")->quantity);

    struct item probe;
    item_init(&probe, "probe", 9, 1);
    long off = report_field_offset("quantity");
    printf("offset_ok %d\n", off >= 0 && *(int *)((char *)&probe + off) == 9);

    report_csv(stdout, &inv);
    return 0;
}
