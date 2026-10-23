import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import HistoryCompactor
import MemoryUpdater
import MindStores
from MindStores import SURFACE_ASSISTANT, SURFACE_COMPANION, surface_scope
from mind_test_utils import TempMindTestCase


class PersonaChatHistoryTests(TempMindTestCase):
    def setUp(self):
        super().setUp()
        self.db_path = self.db(SURFACE_COMPANION)
        self.engine_kwargs = {"reflection_every_n_turns": 100, "surface": SURFACE_COMPANION}

    def test_legacy_history_is_migrated_to_main(self):
        self.db_path.parent.mkdir(parents=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE chat_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO chat_logs (role, content) VALUES ('user', 'legacy')"
            )

        MemoryUpdater.ensure_mind_db(SURFACE_COMPANION)

        with sqlite3.connect(self.db_path) as conn:
            columns = {
                row[1]: row for row in conn.execute("PRAGMA table_info(chat_logs)")
            }
            persona_ids = [
                row[0] for row in conn.execute("SELECT persona_id FROM chat_logs")
            ]
            indexes = {
                row[1] for row in conn.execute("PRAGMA index_list(chat_logs)")
            }

        self.assertEqual(persona_ids, [MemoryUpdater.DEFAULT_PERSONA_ID])
        self.assertEqual(columns["persona_id"][3], 1)
        self.assertIn("surface", columns)
        self.assertIn("idx_chat_logs_persona_id", indexes)
        self.assertIn("idx_chat_logs_persona_surface", indexes)

    def test_history_and_reflection_counts_are_scoped_by_active_persona(self):
        engine = MemoryUpdater.CompanionEngine(**self.engine_kwargs)
        engine._log_message("user", "main question")
        engine._log_message("assistant", "main answer")
        engine.create_persona(companion_name="Alt", persona_id="alt")
        engine.activate_persona("alt")
        engine._log_message("user", "alt question")
        engine._log_message("assistant", "alt answer")

        self.assertEqual(
            engine._get_short_term_context(include_timestamps=False),
            [
                {"role": "user", "content": "alt question"},
                {"role": "assistant", "content": "alt answer"},
            ],
        )
        self.assertEqual(engine._assistant_turn_count(), 1)

        engine.activate_persona("main")
        self.assertEqual(
            engine._get_short_term_context(include_timestamps=False),
            [
                {"role": "user", "content": "main question"},
                {"role": "assistant", "content": "main answer"},
            ],
        )
        self.assertEqual(engine._assistant_turn_count(), 1)

    def test_deleting_persona_purges_only_its_short_term_history(self):
        engine = MemoryUpdater.CompanionEngine(**self.engine_kwargs)
        engine._log_message("user", "keep main")
        engine.create_persona(companion_name="Alt", persona_id="alt")
        engine.activate_persona("alt")
        engine._log_message("user", "remove alt")
        engine.activate_persona("main")

        engine.delete_persona("alt")

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT persona_id, content FROM chat_logs ORDER BY id"
            ).fetchall()
        self.assertEqual(rows, [("main", "keep main")])

    def test_compaction_keeps_recent_rows_per_persona(self):
        MemoryUpdater.ensure_mind_db(SURFACE_COMPANION)
        with sqlite3.connect(self.db_path) as conn:
            for turn in range(4):
                for persona_id in ("main", "alt"):
                    conn.execute(
                        """
                        INSERT INTO chat_logs (role, content, persona_id)
                        VALUES (?, ?, ?)
                        """,
                        ("user", f"{persona_id}-{turn}", persona_id),
                    )

        stored_memories = []

        def record_memory(text, **kwargs):
            stored_memories.append((text, kwargs))
            return f"memory-{len(stored_memories)}"

        with (
            patch.object(
                HistoryCompactor,
                "chat_completion",
                return_value="- Shared durable fact",
            ),
            patch.object(HistoryCompactor, "add_memory", side_effect=record_memory),
        ):
            compacted = HistoryCompactor.compact_and_summarize_history(
                keep_last_n=2, surfaces=(SURFACE_COMPANION,)
            )

        with sqlite3.connect(self.db_path) as conn:
            remaining = conn.execute(
                "SELECT persona_id, content FROM chat_logs ORDER BY id"
            ).fetchall()

        self.assertTrue(compacted)
        self.assertEqual(
            remaining,
            [
                ("main", "main-2"),
                ("alt", "alt-2"),
                ("main", "main-3"),
                ("alt", "alt-3"),
            ],
        )
        self.assertEqual(
            {item[1]["metadata"]["persona_id"] for item in stored_memories},
            {"main", "alt"},
        )
        self.assertTrue(
            all(
                item[1]["collection"] == HistoryCompactor.COLLECTION_LIFE
                for item in stored_memories
            )
        )

    def test_anti_invite_notes_and_reply_shape_are_injected(self):
        engine = MemoryUpdater.CompanionEngine(**self.engine_kwargs)
        persona = engine.get_persona()
        self.assertIn("scripted adventure bot", persona.get("personality_notes", ""))
        self.assertNotIn(
            MemoryUpdater.ANTI_INVITE_MARKER,
            persona.get("personality_notes", ""),
        )

        with patch("SemanticMemory.query_memories", return_value=[]):
            prompt = engine.build_persona_system_prompt(
                "hey", prior_user_at=None
            )
        self.assertIn("[REPLY SHAPE — human cadence]", prompt)
        self.assertIn("Occasional", prompt)
        self.assertIn("quest-vending machine", prompt)


class ChatSurfaceIsolationTests(TempMindTestCase):
    """Regression: Companion must never see Assistant/IDE history, persona or memory.

    Persona-scoped chat_logs alone was once mistaken for client isolation, and a
    default surface later let untagged IDE calls land in Companion. Each client now
    has its own DB + Chroma store and there is no default surface.
    """

    def _engines(self):
        companion = MemoryUpdater.get_engine(SURFACE_COMPANION)
        assistant = MemoryUpdater.get_engine(SURFACE_ASSISTANT)
        companion.reflection_every_n_turns = 100
        assistant.reflection_every_n_turns = 100
        return companion, assistant

    def test_normalize_surface_aliases_and_session_heuristic(self):
        self.assertEqual(MindStores.normalize_surface("companion"), SURFACE_COMPANION)
        self.assertEqual(MindStores.normalize_surface("vscode"), SURFACE_ASSISTANT)
        self.assertEqual(
            MindStores.normalize_surface(None, has_session_pack=True), SURFACE_ASSISTANT
        )
        self.assertIsNone(MindStores.normalize_surface(None, has_session_pack=False))

    def test_no_default_surface(self):
        self.assertIsNone(MindStores.current_surface())
        with self.assertRaises(MindStores.SurfaceRequiredError):
            MindStores.require_surface()
        with self.assertRaises(MindStores.SurfaceRequiredError):
            MemoryUpdater.CompanionEngine()

    def test_each_surface_has_its_own_db(self):
        companion, assistant = self._engines()
        self.assertNotEqual(companion.db_path, assistant.db_path)
        self.assertTrue(companion.db_path.endswith("CompanionMind.db"))
        self.assertTrue(assistant.db_path.endswith("AssistantMind.db"))

    def test_assistant_coding_turns_do_not_appear_in_companion_context(self):
        companion, assistant = self._engines()
        with surface_scope(SURFACE_COMPANION):
            companion._log_message("user", "hey Haruhi")
            companion._log_message("assistant", "What now, Czyrus?!")
        with surface_scope(SURFACE_ASSISTANT):
            assistant._log_message("user", "write def add(a, b) in Python")
            assistant._log_message(
                "assistant", "```python\ndef add(a, b):\n    return a + b\n```"
            )

        with surface_scope(SURFACE_COMPANION):
            companion_ctx = companion._get_short_term_context(include_timestamps=False)
        self.assertEqual(
            companion_ctx,
            [
                {"role": "user", "content": "hey Haruhi"},
                {"role": "assistant", "content": "What now, Czyrus?!"},
            ],
        )
        with surface_scope(SURFACE_ASSISTANT):
            assistant_ctx = assistant._get_short_term_context(include_timestamps=False)
        self.assertEqual(len(assistant_ctx), 2)
        self.assertIn("def add", assistant_ctx[1]["content"])

    def test_engine_refuses_other_surface(self):
        companion, _assistant = self._engines()
        with surface_scope(SURFACE_ASSISTANT):
            with self.assertRaises(MindStores.SurfaceMismatchError):
                companion._log_message("user", "fix my docker file")
        with sqlite3.connect(companion.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM chat_logs").fetchone()[0], 0)

    def test_build_chat_messages_ignores_assistant_history(self):
        companion, assistant = self._engines()
        with surface_scope(SURFACE_ASSISTANT):
            assistant._log_message("user", "fix the docker compose leak")
            assistant._log_message(
                "assistant", "```yaml\nservices:\n  app:\n    image: app\n```"
            )

        with surface_scope(SURFACE_COMPANION), patch(
            "SemanticMemory.query_memories", return_value=[]
        ):
            messages = companion.build_chat_messages("how are you?", history_limit=12)

        joined = "\n".join(m["content"] for m in messages)
        self.assertIn("how are you?", joined)
        self.assertNotIn("docker", joined.lower())
        self.assertNotIn("```yaml", joined)

    def test_bleed_detector_scrubs_code_from_companion_history(self):
        companion, _ = self._engines()
        with surface_scope(SURFACE_COMPANION):
            companion._log_message(
                "assistant", "Here:\n```python\nprint('leak')\n```\nDone."
            )
            with self.assertLogs("MemoryUpdater", level="WARNING"):
                ctx = companion._get_short_term_context(include_timestamps=False)
        self.assertNotIn("print('leak')", ctx[0]["content"])
        self.assertIn("[code omitted]", ctx[0]["content"])

    def test_reflection_counts_are_per_store(self):
        companion, assistant = self._engines()
        with surface_scope(SURFACE_ASSISTANT):
            assistant._log_message("assistant", "coding dump")
        with surface_scope(SURFACE_COMPANION):
            companion._log_message("assistant", "haruhi jab")
            self.assertEqual(companion._assistant_turn_count(), 1)
        with surface_scope(SURFACE_ASSISTANT):
            self.assertEqual(assistant._assistant_turn_count(), 1)

        reflected = []

        def fake_reflect():
            reflected.append(True)
            return {"companion_name": "Haruhi Suzumiya"}

        assistant.reflection_every_n_turns = 1
        companion.reflection_every_n_turns = 1
        with surface_scope(SURFACE_ASSISTANT), patch.object(
            assistant, "execute_self_reflection", side_effect=fake_reflect
        ):
            assistant._log_message("assistant", "more coding")
        self.assertEqual(reflected, [], "Assistant reflection is opt-in")
        with surface_scope(SURFACE_COMPANION), patch.object(
            companion, "execute_self_reflection", side_effect=fake_reflect
        ):
            companion._set_last_reflection_assistant_count(0)
            companion._log_message("assistant", "companion reply")
        self.assertEqual(reflected, [True])

    def test_quarantine_moves_legacy_coding_dumps_out_of_companion(self):
        db = self.db(SURFACE_COMPANION)
        MemoryUpdater.ensure_mind_db(SURFACE_COMPANION)
        with sqlite3.connect(db) as conn:
            conn.execute(
                """
                INSERT INTO chat_logs (role, content, persona_id, surface)
                VALUES ('assistant', '```python\ndef add(a, b):\n  return a+b\n```',
                        'main', 'companion')
                """
            )
            conn.execute(
                """
                INSERT INTO chat_logs (role, content, persona_id, surface)
                VALUES ('assistant', 'Bored. Got anything actually interesting?',
                        'main', 'companion')
                """
            )
            conn.execute(
                "DELETE FROM evolution_matrix WHERE key=?",
                (MemoryUpdater.CHAT_SURFACE_ISOLATION_KEY,),
            )

        MemoryUpdater.ensure_mind_db(SURFACE_COMPANION)

        with sqlite3.connect(db) as conn:
            rows = {
                content: surface
                for content, surface in conn.execute(
                    "SELECT content, surface FROM chat_logs ORDER BY id"
                )
            }
        self.assertEqual(rows["```python\ndef add(a, b):\n  return a+b\n```"], "assistant")
        self.assertEqual(rows["Bored. Got anything actually interesting?"], "companion")

    def test_compaction_never_archives_assistant_rows_into_life(self):
        for surface in (SURFACE_COMPANION, SURFACE_ASSISTANT):
            MemoryUpdater.ensure_mind_db(surface)
            with sqlite3.connect(self.db(surface)) as conn:
                for turn in range(4):
                    conn.execute(
                        "INSERT INTO chat_logs (role, content, persona_id) VALUES (?, ?, 'main')",
                        ("user", f"{surface}-{turn}"),
                    )

        stored_memories = []

        def record_memory(text, **kwargs):
            stored_memories.append((text, kwargs))
            return f"memory-{len(stored_memories)}"

        with (
            patch.object(
                HistoryCompactor, "chat_completion", return_value="- Companion-only fact"
            ),
            patch.object(HistoryCompactor, "add_memory", side_effect=record_memory),
        ):
            compacted = HistoryCompactor.compact_and_summarize_history(keep_last_n=2)

        self.assertTrue(compacted)
        self.assertEqual(len(stored_memories), 1)
        self.assertEqual(stored_memories[0][1]["metadata"]["surface"], SURFACE_COMPANION)
        for surface in (SURFACE_COMPANION, SURFACE_ASSISTANT):
            with sqlite3.connect(self.db(surface)) as conn:
                remaining = [r[0] for r in conn.execute("SELECT content FROM chat_logs ORDER BY id")]
            self.assertEqual(remaining, [f"{surface}-2", f"{surface}-3"])


class RequestSurfaceResolutionTests(unittest.TestCase):
    def test_explicit_tag_beats_session_pack(self):
        self.assertEqual(
            MindStores.resolve_request_surface(
                body={"blossom_client": "companion", "blossom_session": "prior turns…"}
            ),
            SURFACE_COMPANION,
        )
        self.assertEqual(
            MindStores.resolve_request_surface(body={"blossom_session": "prior turns…"}),
            SURFACE_ASSISTANT,
        )

    def test_header_beats_body(self):
        self.assertEqual(
            MindStores.resolve_request_surface(
                header="assistant", body={"blossom_client": "companion"}
            ),
            SURFACE_ASSISTANT,
        )

    def test_untagged_strict_is_rejected(self):
        with self.assertRaises(MindStores.SurfaceRequiredError):
            MindStores.resolve_request_surface(body={}, require=True)

    def test_untagged_lenient_never_lands_in_companion(self):
        self.assertEqual(
            MindStores.resolve_request_surface(body={}, require=False), SURFACE_ASSISTANT
        )

    def test_unknown_tag_is_rejected(self):
        with self.assertRaises(MindStores.SurfaceRequiredError):
            MindStores.resolve_request_surface(body={"blossom_client": "web"})

    def test_pinned_router_rejects_other_client(self):
        with patch.dict("os.environ", {"BLOSSOM_SURFACE": "companion"}):
            with self.assertRaises(MindStores.SurfaceMismatchError):
                MindStores.resolve_request_surface(header="assistant")
            self.assertEqual(
                MindStores.resolve_request_surface(body={}, require=True),
                SURFACE_COMPANION,
            )


class TemporalAwarenessTests(TempMindTestCase):
    def setUp(self):
        super().setUp()
        self.db_path = self.db(SURFACE_COMPANION)
        self._scope = surface_scope(SURFACE_COMPANION)
        self._scope.__enter__()

    def tearDown(self):
        self._scope.__exit__(None, None, None)
        super().tearDown()

    def test_humanize_and_memory_age(self):
        from datetime import datetime, timedelta, timezone

        import TemporalContext
        from SemanticMemory import format_memories_for_prompt

        now = datetime(2026, 7, 27, 18, 0, tzinfo=timezone.utc)
        self.assertEqual(
            TemporalContext.humanize_delta(timedelta(days=3)),
            "3 days ago",
        )
        age = TemporalContext.relative_age(
            (now - timedelta(weeks=3)).isoformat(),
            now=now,
        )
        self.assertEqual(age, "3 weeks ago")

        with patch(
            "SemanticMemory.relative_age",
            side_effect=lambda created_at, **kwargs: TemporalContext.relative_age(
                created_at, now=now
            ),
        ):
            block = format_memories_for_prompt(
                [
                    {
                        "text": "We picked the name Blossom.",
                        "metadata": {
                            "created_at": (now - timedelta(days=10)).isoformat()
                        },
                    }
                ]
            )
        self.assertIn("(10 days ago)", block)
        self.assertIn("We picked the name Blossom.", block)

    def test_system_prompt_includes_clock_and_gap(self):
        from datetime import datetime, timedelta

        engine = MemoryUpdater.CompanionEngine(reflection_every_n_turns=100)
        old = (datetime.now().astimezone() - timedelta(days=3)).replace(
            microsecond=0
        ).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO chat_logs (role, content, persona_id, created_at)
                VALUES ('user', 'old hello', 'main', ?)
                """,
                (old,),
            )

        prior = engine._last_user_message_at()
        with patch("SemanticMemory.query_memories", return_value=[]):
            prompt = engine.build_persona_system_prompt(
                "back again", prior_user_at=prior
            )
        self.assertIn("[TEMPORAL CONTEXT]", prompt)
        self.assertIn("Local time now:", prompt)
        self.assertIn("3 days ago", prompt)
        self.assertIn("Days have passed", prompt)

    def test_build_chat_messages_stamps_history_and_preserves_gap(self):
        from datetime import datetime, timedelta

        engine = MemoryUpdater.CompanionEngine(reflection_every_n_turns=100)
        old = (datetime.now().astimezone() - timedelta(hours=5)).replace(
            microsecond=0
        ).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO chat_logs (role, content, persona_id, created_at)
                VALUES ('user', 'earlier', 'main', ?)
                """,
                (old,),
            )
            conn.execute(
                """
                INSERT INTO chat_logs (role, content, persona_id, created_at)
                VALUES ('assistant', 'hi back', 'main', ?)
                """,
                (old,),
            )

        with (
            patch("SemanticMemory.query_memories", return_value=[]),
            patch.object(
                engine,
                "build_persona_system_prompt",
                wraps=engine.build_persona_system_prompt,
            ) as prompt_spy,
        ):
            messages = engine.build_chat_messages("new ping", history_limit=8)

        kwargs = prompt_spy.call_args.kwargs
        self.assertEqual(kwargs.get("prior_user_at"), old)

        system = messages[0]["content"]
        self.assertIn("[TEMPORAL CONTEXT]", system)
        self.assertIn("5 hour", system)

        stamped = [m for m in messages if m["role"] != "system"]
        self.assertTrue(any(m["content"].startswith("[") for m in stamped))
        self.assertTrue(
            any("new ping" in m["content"] for m in stamped if m["role"] == "user")
        )


if __name__ == "__main__":
    unittest.main()
