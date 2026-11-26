#ifndef TEXTSTATS_GRADES_H
#define TEXTSTATS_GRADES_H

#include <stddef.h>

struct grade_summary {
    int mean;
    int median;
};

/* Clamps every score to 0..100 in place, then summarizes. */
struct grade_summary grades_summarize(int *scores, size_t n);

#endif
