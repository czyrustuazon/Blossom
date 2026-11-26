#ifndef TEXTSTATS_UTIL_H
#define TEXTSTATS_UTIL_H

#include <stddef.h>

/* ---- strings ---- */

/* Removes leading and trailing whitespace in place; returns s. */
char *str_trim(char *s);
/* Number of whitespace-separated words. */
int str_count_words(const char *s);
/* Upper-cases ASCII letters in place; returns s. */
char *str_to_upper(char *s);

/* ---- math ---- */

#define UTIL_MAX_SAMPLES 64

int clamp_int(int v, int lo, int hi);
/* Integer mean rounded toward zero; 0 for n == 0. */
int mean_int(const int *xs, size_t n);
/* Median of up to UTIL_MAX_SAMPLES values (lower middle for even n); 0 for n == 0. */
int median_int(const int *xs, size_t n);

#endif
