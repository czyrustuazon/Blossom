#ifndef TEXTSTATS_WORDCOUNT_H
#define TEXTSTATS_WORDCOUNT_H

#include <stddef.h>

struct line_stats {
    int lines;
    int words;
    int mean_words;  /* words per non-empty line */
};

/* Counts words over `n` lines; trims each line in place first, skips empty lines. */
struct line_stats wordcount_lines(char **lines, size_t n);

/* Upper-cases and trims a heading in place. */
char *wordcount_heading(char *s);

#endif
