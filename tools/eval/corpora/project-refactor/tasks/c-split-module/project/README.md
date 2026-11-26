# textstats

Small C11 helpers for counting words and summarizing grades.

## Layout

- `src/util.c`, `src/util.h` — shared helpers: string functions (`str_trim`, `str_count_words`,
  `str_to_upper`) and math functions (`clamp_int`, `mean_int`, `median_int`, `UTIL_MAX_SAMPLES`).
- `src/wordcount.c` — per-line word statistics.
- `src/grades.c` — clamps scores to 0..100 and reports mean and median.

## Tests

```
python -m pytest tests
```

The tests build every `src/*.c` file with `tests/driver.c` using gcc (`-Wall -Wextra -Werror`).
