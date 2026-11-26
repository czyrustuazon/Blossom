#ifndef TEXTSTATS_MATHUTIL_H
#define TEXTSTATS_MATHUTIL_H

#include <stddef.h>

#define UTIL_MAX_SAMPLES 64

int clamp_int(int v, int lo, int hi);
/* Integer mean rounded toward zero; 0 for n == 0. */
int mean_int(const int *xs, size_t n);
/* Median of up to UTIL_MAX_SAMPLES values (lower middle for even n); 0 for n == 0. */
int median_int(const int *xs, size_t n);

#endif
