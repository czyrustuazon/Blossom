#include "grades.h"
#include "util.h"

struct grade_summary grades_summarize(int *scores, size_t n)
{
    for (size_t i = 0; i < n; i++)
        scores[i] = clamp_int(scores[i], 0, 100);
    struct grade_summary g = { mean_int(scores, n), median_int(scores, n) };
    return g;
}
