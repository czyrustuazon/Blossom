import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import HistoryCompactor
import MemoryUpdater


class PersonaChatHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mind_dir = Path(self.temp_dir.name) / "Mind"
        self.db_path = self.mind_dir / "CompanionMind.db"
        self.db_patch = patch.object(MemoryUpdater, "DB_PATH", self.db_path)
        self.mind_patch = patch.object(MemoryUpdater, "MIND_DIR", self.mind_dir)
        self.db_patch.start()
        self.mind_patch.start()

    def tearDown(self):
        self.mind_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_legacy_history_is_migrated_to_main(self):
        self.mind_dir.mkdir(parents=True)
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

        MemoryUpdater.ensure_mind_db()

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
        self.assertIn("idx_chat_logs_persona_id", indexes)

    def test_history_and_reflection_counts_are_scoped_by_active_persona(self):
        engine = MemoryUpdater.CompanionEngine(reflection_every_n_turns=100)
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
        engine = MemoryUpdater.CompanionEngine(reflection_every_n_turns=100)
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
        MemoryUpdater.ensure_mind_db()
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
            patch.object(HistoryCompactor, "DB_PATH", self.db_path),
            patch.object(HistoryCompactor, "ensure_mind_db"),
            patch.object(
                HistoryCompactor,
                "chat_completion",
                return_value="- Shared durable fact",
            ),
            patch.object(HistoryCompactor, "add_memory", side_effect=record_memory),
        ):
            compacted = HistoryCompactor.compact_and_summarize_history(keep_last_n=2)

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
        engine = MemoryUpdater.CompanionEngine(reflection_every_n_turns=100)
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


class TemporalAwarenessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mind_dir = Path(self.temp_dir.name) / "Mind"
        self.db_path = self.mind_dir / "CompanionMind.db"
        self.db_patch = patch.object(MemoryUpdater, "DB_PATH", self.db_path)
        self.mind_patch = patch.object(MemoryUpdater, "MIND_DIR", self.mind_dir)
        self.db_patch.start()
        self.mind_patch.start()

    def tearDown(self):
        self.mind_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

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
