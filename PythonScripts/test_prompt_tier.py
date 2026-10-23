"""Tests for prompt tier detection."""

from PromptTier import PromptTier, detect_prompt_tier, should_skip_coding_lessons


def test_detect_plan_tier():
    assert detect_prompt_tier("How should we organize this into MVC?") == PromptTier.PLAN


def test_detect_tiny_tier_with_editor():
    text = "[EDITOR CONTEXT]\npath=index.html\n\nfix the typo in the title"
    assert detect_prompt_tier(text) == PromptTier.TINY


def test_clue_ask_is_plan():
    assert detect_prompt_tier("Examine hand-off.md to get an idea what to do next") == PromptTier.PLAN
    assert detect_prompt_tier("Use progress.md as a guide and then implement it") == PromptTier.FULL


def test_fix_list_inside_attached_doc_does_not_flip_to_execute():
    text = (
        "[EDITOR CONTEXT]\n<<<FILE path=\"hand-off.md\">>>\n"
        "1. Fix the router bug\n2. Add the save hook\n3. Remove dead code\n<<<END_FILE>>>\n"
        "[USER REQUEST]\nRead hand-off.md so you know what to do"
    )
    assert detect_prompt_tier(text) == PromptTier.PLAN


def test_skip_lessons_on_tiny():
    text = "[EDITOR CONTEXT]\npath=a.html\n\nadd a link"
    assert should_skip_coding_lessons(PromptTier.TINY, user_prompt=text)
