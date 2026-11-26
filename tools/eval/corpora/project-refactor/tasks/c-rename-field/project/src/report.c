#include <stddef.h>
#include <string.h>

#include "report.h"

struct field_desc {
    const char *column;
    size_t offset;
};

static const struct field_desc INT_FIELDS[] = {
    { "qty", offsetof(struct item, qty) },
    { "price_cents", offsetof(struct item, price_cents) },
};

void report_csv(FILE *out, const struct inventory *inv)
{
    fprintf(out, "name,qty,price_cents\n");
    for (int i = 0; i < inv->count; i++) {
        const struct item *it = &inv->items[i];
        fprintf(out, "%s,%d,%d\n", it->name, it->qty, it->price_cents);
    }
}

long report_field_offset(const char *field)
{
    for (size_t i = 0; i < sizeof INT_FIELDS / sizeof INT_FIELDS[0]; i++)
        if (strcmp(INT_FIELDS[i].column, field) == 0)
            return (long)INT_FIELDS[i].offset;
    return -1;
}
