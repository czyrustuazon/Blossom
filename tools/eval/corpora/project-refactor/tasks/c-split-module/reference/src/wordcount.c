#include "mathutil.h"
#include "strutil.h"
#include "wordcount.h"

struct line_stats wordcount_lines(char **lines, size_t n)
{
    struct line_stats st = { 0, 0, 0 };
    int counts[UTIL_MAX_SAMPLES];
    size_t kept = 0;
    for (size_t i = 0; i < n; i++) {
        str_trim(lines[i]);
        if (lines[i][0] == '\0')
            continue;
        int w = str_count_words(lines[i]);
        st.lines++;
        st.words += w;
        if (kept < UTIL_MAX_SAMPLES)
            counts[kept++] = w;
    }
    st.mean_words = mean_int(counts, kept);
    return st;
}

char *wordcount_heading(char *s)
{
    return str_to_upper(str_trim(s));
}
