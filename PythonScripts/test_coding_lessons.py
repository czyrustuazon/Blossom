"""
Auto-learned coding lessons must be solutions, not the coder's own non-answers.

Texts below are real answers that ChatRouter stored as "Working solution" in coding_lessons
(user's PHP refactor asks, 2026-11) or that the coder produced in the real-extension eval
(2026-11-21). Retrieved into later prompts, the coder copied them: it announced work and
stopped, or asked the user to share files it could read itself.
"""
from __future__ import annotations

from SemanticMemory import looks_like_non_solution


def _lesson(answer: str) -> str:
    return (
        "User ask: refactor this project to be more php compliant in 2026\n"
        "Working solution (local_coder:NVIDIA-Nemotron-3.5-Lightning-30B-A3B-IQ4_XS.gguf):\n"
        + answer
    )


INTENT_ONE_PARAGRAPH = (
    "Looking at this task, I need to refactor `gallery.php` to be more PHP compliant in 2026. "
    "The most critical issue is the use of deprecated `mysql_*` functions (removed in PHP 7+). "
    "Let me first identify all the mysql_* calls in the file."
)

INTENT_AFTER_PLAN = (
    "Looking at the attached `gallery.php` file, I can see it's a PHP gallery website that uses "
    "deprecated `mysql_*` functions.\n\n## PLAN\n\n"
    "1. **Research** - Analyze the existing code structure\n"
    "2. **Modernize PHP tags** - Change `<?PHP` to `<?php` throughout\n"
    "3. **Replace `mysql_*` with `mysqli_*`** - Using prepared statements for security\n\n"
    "Let me start by examining the file structure and then create the modernized version."
)

EMPTY_FENCE_THEN_LABEL = (
    "```php\n``` path=gallery.php\n<?PHP\nrequire_once(\"includes/text_filter.php\");\n"
    "session_start();\n"
)

ASKS_FOR_FILES = (
    "I can see index.js imports ./store.js, but it was not attached. If you can share store.js "
    "and util.js, I can do the conversion to async/await."
)

CANNOT_SEE = "I don't have access to the other files in the project, so here is the general approach."

GOOD_CODE = "```python path=add_function.py\ndef add(a, b):\n    return a + b\n```"

GOOD_EXPLAINED = (
    "The bug is the off-by-one in the loop bound.\n\n"
    "```python\nfor i in range(len(items)):\n    total += items[i]\nreturn total\n```\n\n"
    "Let me know if you want tests for it."
)

NLPP_SEED = (
    "[NLPP seed: ui | ui-opaque-softkeys-bclim] Symptom: opaque softkeys / labels still JP "
    "(Back/Next/OK/Quit). Cause: chrome is baked into BCLIM textures. Fix: redraw the plates."
)


def test_intent_only_answers_are_not_solutions():
    assert looks_like_non_solution(_lesson(INTENT_ONE_PARAGRAPH))
    assert looks_like_non_solution(_lesson(INTENT_AFTER_PLAN))


def test_broken_fence_label_is_not_a_solution():
    assert looks_like_non_solution(_lesson(EMPTY_FENCE_THEN_LABEL))


def test_asking_for_files_is_not_a_solution():
    assert looks_like_non_solution(_lesson(ASKS_FOR_FILES))
    assert looks_like_non_solution(CANNOT_SEE)


def test_real_solutions_are_kept():
    assert not looks_like_non_solution(_lesson(GOOD_CODE))
    # A closing "Let me know…" after real code is a courtesy, not an unfinished answer.
    assert not looks_like_non_solution(_lesson(GOOD_EXPLAINED))
    assert not looks_like_non_solution(NLPP_SEED)


def test_user_ask_part_is_ignored():
    # "please share" in the user's ask must not hide the coder's real answer.
    text = (
        "User ask: please share a function that adds two numbers\n"
        "Working solution (x):\n" + GOOD_CODE
    )
    assert not looks_like_non_solution(text)
