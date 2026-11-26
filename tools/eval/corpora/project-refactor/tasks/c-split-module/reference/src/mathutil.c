#include <stdlib.h>
#include <string.h>

#include "mathutil.h"

static int cmp_int(const void *a, const void *b)
{
    int x = *(const int *)a, y = *(const int *)b;
    return (x > y) - (x < y);
}

int clamp_int(int v, int lo, int hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

int mean_int(const int *xs, size_t n)
{
    if (n == 0)
        return 0;
    long sum = 0;
    for (size_t i = 0; i < n; i++)
        sum += xs[i];
    return (int)(sum / (long)n);
}

int median_int(const int *xs, size_t n)
{
    if (n == 0)
        return 0;
    int tmp[UTIL_MAX_SAMPLES];
    n = n > UTIL_MAX_SAMPLES ? UTIL_MAX_SAMPLES : n;
    memcpy(tmp, xs, n * sizeof *xs);
    qsort(tmp, n, sizeof *tmp, cmp_int);
    return tmp[(n - 1) / 2];
}
