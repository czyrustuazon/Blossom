#ifndef TEXTSTATS_STRUTIL_H
#define TEXTSTATS_STRUTIL_H

/* Removes leading and trailing whitespace in place; returns s. */
char *str_trim(char *s);
/* Number of whitespace-separated words. */
int str_count_words(const char *s);
/* Upper-cases ASCII letters in place; returns s. */
char *str_to_upper(char *s);

#endif
