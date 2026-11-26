#include <stdlib.h>
#include <string.h>

#include "util.h"

/* ---- strings ---- */

static int is_space(char c)
{
    return c == ' ' || c == '\t' || c == '\n' || c == '\r';
}

char *str_trim(char *s)
{
    char *start = s;
    while (*start && is_space(*start))
        start++;
    size_t len = strlen(start);
    while (len > 0 && is_space(start[len - 1]))
        len--;
    memmove(s, start, len);
    s[len] = '\0';
    return s;
}

int str_count_words(const char *s)
{
    int words = 0, in_word = 0;
    for (; *s; s++) {
        if (is_space(*s)) {
            in_word = 0;
        } else if (!in_word) {
            in_word = 1;
            words++;
        }
    }
    return words;
}

char *str_to_upper(char *s)
{
    for (char *p = s; *p; p++)
        if (*p >= 'a' && *p <= 'z')
            *p = (char)(*p - 'a' + 'A');
    return s;
}

/* ---- math ---- */

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
