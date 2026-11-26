#ifndef INVKIT_REPORT_H
#define INVKIT_REPORT_H

#include <stdio.h>

#include "inventory.h"

/* Writes the inventory as CSV: a header line, then one line per item. */
void report_csv(FILE *out, const struct inventory *inv);

/* Byte offset of a named int field of struct item, or -1. Used by the CSV importer. */
long report_field_offset(const char *field);

#endif
