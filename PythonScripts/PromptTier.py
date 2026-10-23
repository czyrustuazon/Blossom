"""Prompt tier detection — shorter prompts for plan-only and tiny-edit turns."""

from __future__ import annotations

import re
from enum import Enum

from EditorContext import extract_user_request, looks_like_editor_dump

PLAN_FIRST_RE = re.compile(
    r"\b("
    r"where should we begin|how should we|what would you recommend|thoughts\?|"
    r"does this make sense|roadmap|outline|pros/cons|before we change|"
    r"best way to|organize|restructure|architecture|folder layout|"
    r"mvc|approach\?|plan\?"
    r")\b",
    re.I,
)
ACTIONABLE_RE = re.compile(
    r"\b("
    r"fix|add|create|delete|remove|implement|refactor|update|rename|"
    r"apply|do it|go ahead|start coding|write a function|bug|error"
    r")\b",
    re.I,
)
APPROVAL_RE = re.compile(
    r"\b(do it|go ahead|implement|start|yes\b|apply now|continue)\b",
    re.I,
)
MULTI_FILE_RE = re.compile(
    r"\b(and|multiple|all files|entire repo|refactor entire|every file)\b",
    re.I,
)
# Mirrors CLUE_ASK_RE in the extension's promptTier.ts: reference-as-clue → blueprint.
CLUE_ASK_RE = re.compile(
    r"\b(?:(?:to |so (?:you|we|that you|that we) )?(?:get|have|form) (?:an? |some )?"
    r"(?:idea|sense|picture|feel) (?:of |for |about )?(?:what|how|where)|"
    r"so (?:you|we) (?:know|understand|can figure out|can decide) (?:what|how|where)|"
    r"to (?:figure out|work out|decide|understand|learn) (?:what|how|where) "
    r"(?:to do|we should|you should|needs?|comes?|is next)|"
    r"(?:as|for) (?:a |the )?(?:clue|clues|guide|guidance|hint|hints|reference|"
    r"starting point|inspiration|blueprint|roadmap)|"
    r"use (?:it|this|that|them|[\w./\\-]+) to (?:guide|inform)|what to do next)\b",
    re.I,
)
CLUE_IMPLEMENT_OVERRIDE_RE = re.compile(
    r"\b(?:do it|go ahead|implement (?:it|now|them|the (?:plan|changes|fix(?:es)?|steps))|"
    r"apply (?:it|them|now)|start (?:coding|implementing)|"
    r"then (?:implement|apply|fix|make the changes|do the changes))\b",
    re.I,
)

PLAN_ONLY_CODER_PROMPT = (
    "You are Blossom's coding planner. RESEARCH tools are allowed.\n"
    "Output UNDERSTAND + PLAN checklist only — no write_file, delete_file, or "
    "path-labeled file fences until the user approves implementation.\n"
    "End with ### Summary of the plan and offer to implement."
)

TINY_EDIT_CODER_PROMPT = (
    "You are Blossom's coding agent. Editor context is complete — minimal RESEARCH, "
    "then PLAN → EXECUTE the smallest correct change → VERIFY → ### Summary.\n"
    "Use path-labeled fences (one file per fence). Preserve existing content unless "
    "the user asked for a full rewrite."
)


class PromptTier(str, Enum):
    FULL = "full"
    PLAN = "plan"
    TINY = "tiny"


def has_editor_context(user_prompt: str) -> bool:
    text = user_prompt or ""
    return looks_like_editor_dump(text) or "[EDITOR CONTEXT]" in text


def detect_prompt_tier(user_prompt: str) -> PromptTier:
    """Fallback when the host sent no blossom_tier. Classifies the user's sentence only:
    edit verbs inside attached files or agent instructions must not flip it to execute."""
    full_text = (user_prompt or "").strip()
    if not full_text:
        return PromptTier.FULL

    has_editor = has_editor_context(full_text)
    text = extract_user_request(full_text)
    if CLUE_ASK_RE.search(text) and not CLUE_IMPLEMENT_OVERRIDE_RE.search(text):
        return PromptTier.PLAN

    planish = bool(PLAN_FIRST_RE.search(text))
    actionable = bool(ACTIONABLE_RE.search(text))
    approved = bool(APPROVAL_RE.search(text))

    if approved or (actionable and not planish):
        if (
            has_editor
            and len(full_text) < 1200
            and not MULTI_FILE_RE.search(text)
        ):
            return PromptTier.TINY
        return PromptTier.FULL

    if planish or re.search(r"\b(plan|approach)\b", text, re.I):
        return PromptTier.PLAN

    return PromptTier.FULL


def should_skip_coding_lessons(tier: PromptTier, *, user_prompt: str) -> bool:
    return tier == PromptTier.TINY and has_editor_context(user_prompt)


def coder_system_prompt_for_tier(tier: PromptTier, full_prompt: str) -> str:
    if tier == PromptTier.PLAN:
        return PLAN_ONLY_CODER_PROMPT
    if tier == PromptTier.TINY:
        return TINY_EDIT_CODER_PROMPT
    return full_prompt
