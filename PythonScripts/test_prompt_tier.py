"""Tests for prompt tier detection."""

from PromptTier import PromptTier, detect_prompt_tier, should_skip_coding_lessons


def test_detect_plan_tier():
    assert detect_prompt_tier("How should we organize this into MVC?") == PromptTier.PLAN


def test_detect_tiny_tier_with_editor():
    text = "[EDITOR CONTEXT]\npath=index.html\n\nfix the typo in the title"
    assert detect_prompt_tier(text) == PromptTier.TINY


def test_skip_lessons_on_tiny():
    text = "[EDITOR CONTEXT]\npath=a.html\n\nadd a link"
    assert should_skip_coding_lessons(PromptTier.TINY, user_prompt=text)
