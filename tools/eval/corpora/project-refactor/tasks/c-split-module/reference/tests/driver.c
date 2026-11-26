/* Test driver: exercises the library and prints results that test_textstats.py checks. */
#include <stdio.h>
#include <string.h>

#include "grades.h"
#include "mathutil.h"
#include "strutil.h"
#include "wordcount.h"

int main(void)
{
    char a[] = "  the quick brown fox  ";
    char b[] = "\t\t";
    char c[] = "jumps over\tthe lazy dog\n";
    char *lines[] = { a, b, c };
    struct line_stats st = wordcount_lines(lines, 3);
    printf("lines %d words %d mean %d\n", st.lines, st.words, st.mean_words);
    printf("trimmed [%s]\n", a);

    char h[] = "  chapter one ";
    printf("heading [%s]\n", wordcount_heading(h));

    int scores[] = { 88, 104, 67, -5, 91 };
    struct grade_summary g = grades_summarize(scores, 5);
    printf("mean %d median %d clamped %d %d\n", g.mean, g.median, scores[1], scores[3]);

    int none[1] = { 0 };
    printf("empty %d %d\n", mean_int(none, 0), median_int(none, 0));
    printf("clamp %d %d %d\n", clamp_int(-3, 0, 9), clamp_int(5, 0, 9), clamp_int(12, 0, 9));

    char w[] = "one two  three";
    printf("count %d upper [%s]\n", str_count_words(w), str_to_upper(w));
    return 0;
}
