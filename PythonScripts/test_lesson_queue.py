"""Auto-learned coding lessons wait in a review queue; only approved ones reach the Mind."""
from __future__ import annotations

import pytest

import FeedbackStore
import LessonQueue
import MindStores
import SemanticMemory
from MindStores import SURFACE_ASSISTANT, SURFACE_COMPANION
from review_lessons import main as review_main

ASK = "Write a Python function add(a, b) that returns the sum."
ANSWER = "```python path=add.py\ndef add(a, b):\n    return a + b\n```"


@pytest.fixture(autouse=True)
def _fresh_queue(monkeypatch):
    monkeypatch.delenv("LESSON_QUEUE", raising=False)
    path = LessonQueue.db_file()
    if path.exists():
        path.unlink()
    yield


def _stored_texts() -> list[str]:
    with MindStores.surface_scope(SURFACE_ASSISTANT):
        coll = SemanticMemory._get_collection(SemanticMemory.COLLECTION_CODING)
        return coll.get()["documents"]


def _learn() -> str | None:
    with MindStores.surface_scope(SURFACE_ASSISTANT):
        return SemanticMemory.learn_coding_lesson(ASK, ANSWER, source="test_coder")


def test_learned_lesson_is_queued_not_stored():
    before = len(_stored_texts())
    qid = _learn()
    assert LessonQueue.is_queued_id(qid)
    assert len(_stored_texts()) == before
    pending = LessonQueue.list_entries()
    assert [e["id"] for e in pending] == [qid.split(":", 1)[1]]
    assert "def add(a, b)" in pending[0]["text"]


def test_approve_stores_and_reject_does_not():
    keep, drop = _learn(), _learn()
    before = len(_stored_texts())
    assert review_main(["approve", keep]) == 0
    assert review_main(["reject", drop.split(":", 1)[1], "--reason", "dup"]) == 0
    assert len(_stored_texts()) == before + 1
    assert LessonQueue.get_entry(keep)["status"] == "approved"
    assert LessonQueue.get_entry(drop)["status"] == "rejected"
    assert LessonQueue.list_entries() == []
    # Reviewed entries cannot be approved again.
    assert LessonQueue.approve(keep) is None


def test_non_answers_are_never_queued():
    with MindStores.surface_scope(SURFACE_ASSISTANT):
        assert SemanticMemory.learn_coding_lesson(
            ASK, "Looking at this, I need to add two numbers. Let me first read the file.", "x"
        ) is None
    assert LessonQueue.list_entries() == []


def test_companion_cannot_queue_coding_lessons():
    with MindStores.surface_scope(SURFACE_COMPANION):
        assert SemanticMemory.learn_coding_lesson(ASK, ANSWER, source="x") is None
    assert LessonQueue.list_entries() == []


def test_feedback_correct_marks_queued_lesson_verified():
    qid = _learn()
    with MindStores.surface_scope(SURFACE_ASSISTANT):
        out = FeedbackStore._resolve_coding(
            verdict="correct", note="", user_prompt=ASK, answer=ANSWER,
            source="test", memory_id=qid, collection=SemanticMemory.COLLECTION_CODING,
        )
    assert out["actions"] == ["verified_queued_lesson"] and out["stored"] is False
    entry = LessonQueue.get_entry(qid)
    assert entry["status"] == "pending" and entry["metadata"]["user_verified"] is True
    assert entry["importance"] == 9


def test_feedback_incorrect_rejects_queued_lesson():
    qid = _learn()
    with MindStores.surface_scope(SURFACE_ASSISTANT):
        out = FeedbackStore._resolve_coding(
            verdict="incorrect", note="", user_prompt=ASK, answer=ANSWER,
            source="test", memory_id=qid, collection=SemanticMemory.COLLECTION_CODING,
        )
    assert "rejected_queued_lesson" in out["actions"]
    assert LessonQueue.get_entry(qid)["status"] == "rejected"


def test_queue_off_stores_directly(monkeypatch):
    monkeypatch.setenv("LESSON_QUEUE", "0")
    before = len(_stored_texts())
    mid = _learn()
    assert mid and not LessonQueue.is_queued_id(mid)
    assert len(_stored_texts()) == before + 1
