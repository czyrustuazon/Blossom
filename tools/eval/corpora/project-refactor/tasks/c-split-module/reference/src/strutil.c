#include <string.h>

#include "strutil.h"

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
