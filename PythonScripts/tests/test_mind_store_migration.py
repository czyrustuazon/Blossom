"""Legacy shared Mind/ → per-client stores migration (idempotent, lossless)."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import chromadb  # noqa: E402
from chromadb.config import Settings  # noqa: E402

import MemoryUpdater  # noqa: E402
import MindStores  # noqa: E402
import SemanticMemory  # noqa: E402
from MindStores import SURFACE_ASSISTANT, SURFACE_COMPANION  # noqa: E402
from mind_test_utils import TempMindTestCase  # noqa: E402


class LegacyMigrationTests(TempMindTestCase):
    def _make_legacy_db(self):
        legacy = self.mind_root / "CompanionMind.db"
        with sqlite3.connect(legacy) as conn:
            conn.execute(
                """
                CREATE TABLE chat_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL, content TEXT NOT NULL,
                    persona_id TEXT NOT NULL DEFAULT 'main',
                    surface TEXT NOT NULL DEFAULT 'companion',
                    created_at TEXT
                )
                """
            )
            conn.execute("CREATE TABLE evolution_matrix (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            book = {
                "active_id": "main",
                "profiles": {
                    "main": {
                        "companion_name": "Haruhi Suzumiya",
                        "relationship_stage": "close friends",
                        "internal_mood_diary": "restless",
                        "perceived_user_traits": ["night owl"],
                        "linguistic_quirks": ["boss energy"],
                        "personality_notes": "SOS Brigade chief.",
                        "voice_id": "haruhi",
                    }
                },
            }
            conn.execute(
                "INSERT INTO evolution_matrix VALUES ('persona_book', ?)", (json.dumps(book),)
            )
            conn.executemany(
                "INSERT INTO chat_logs (role, content, surface) VALUES (?, ?, ?)",
                [
                    ("user", "hey Haruhi", "companion"),
                    ("assistant", "What?!", "companion"),
                    ("user", "write add()", "assistant"),
                    ("assistant", "```python\ndef add(): ...\n```", "assistant"),
                ],
            )
            conn.execute(
                """
                CREATE TABLE feedback_turns (
                    id TEXT PRIMARY KEY, route TEXT NOT NULL, user_prompt TEXT NOT NULL,
                    answer TEXT NOT NULL, source TEXT, memory_id TEXT, collection TEXT,
                    verdict TEXT, note TEXT, result_json TEXT,
                    created_at REAL NOT NULL, resolved_at REAL
                )
                """
            )
            conn.executemany(
                "INSERT INTO feedback_turns (id, route, user_prompt, answer, created_at) "
                "VALUES (?, ?, 'q', 'a', 1.0)",
                [("fb-code", "coding"), ("fb-jp", "japanese")],
            )

    def _make_legacy_chroma(self):
        # Separate process: Chroma keeps its files mapped until the process exits,
        # and the real migration also runs in a fresh router process.
        script = (
            "import sys, chromadb\n"
            "from chromadb.config import Settings\n"
            "c = chromadb.PersistentClient(path=sys.argv[1], "
            "settings=Settings(anonymized_telemetry=False))\n"
            "for name, ids in (('relationship_life', ['life-1']), "
            "('coding_lessons', ['code-1', 'code-2']), ('nlpp_hard_bans', ['ban-1'])):\n"
            "    coll = c.get_or_create_collection(name, metadata={'hnsw:space': 'cosine'})\n"
            "    coll.add(ids=ids, documents=[name + ' ' + i for i in ids],\n"
            "             embeddings=[[0.1 * (n + 1), 0.2, 0.3] for n in range(len(ids))],\n"
            "             metadatas=[{'importance_score': 5} for _ in ids])\n"
        )
        subprocess.run(
            [sys.executable, "-c", script, str(self.mind_root / "chromadb")],
            check=True,
            timeout=120,
        )

    def test_bootstrap_splits_legacy_layout(self):
        self._make_legacy_db()
        self._make_legacy_chroma()

        MemoryUpdater.bootstrap_mind_stores()

        self.assertFalse((self.mind_root / "CompanionMind.db").exists())
        self.assertFalse((self.mind_root / "chromadb").exists())

        with sqlite3.connect(self.db(SURFACE_COMPANION)) as conn:
            companion_rows = conn.execute("SELECT content FROM chat_logs ORDER BY id").fetchall()
            companion_fb = conn.execute("SELECT id FROM feedback_turns").fetchall()
        with sqlite3.connect(self.db(SURFACE_ASSISTANT)) as conn:
            assistant_rows = conn.execute(
                "SELECT content, surface FROM chat_logs ORDER BY id"
            ).fetchall()
            assistant_fb = conn.execute("SELECT id FROM feedback_turns").fetchall()

        self.assertEqual([r[0] for r in companion_rows], ["hey Haruhi", "What?!"])
        self.assertEqual([r[0] for r in assistant_rows], ["write add()", "```python\ndef add(): ...\n```"])
        self.assertTrue(all(r[1] == SURFACE_ASSISTANT for r in assistant_rows))
        self.assertEqual(companion_fb, [("fb-jp",)])
        self.assertEqual(assistant_fb, [("fb-code",)])

        companion_engine = MemoryUpdater.get_engine(SURFACE_COMPANION)
        assistant_engine = MemoryUpdater.get_engine(SURFACE_ASSISTANT)
        with MindStores.surface_scope(SURFACE_COMPANION):
            c_persona = companion_engine.get_persona()
        with MindStores.surface_scope(SURFACE_ASSISTANT):
            a_persona = assistant_engine.get_persona()
        self.assertEqual(c_persona["relationship_stage"], "close friends")
        self.assertEqual(a_persona["companion_name"], "Haruhi Suzumiya")
        self.assertEqual(a_persona["voice_id"], "haruhi")
        self.assertEqual(a_persona["relationship_stage"], "just met")
        self.assertEqual(a_persona["perceived_user_traits"], [])

        SemanticMemory.reset_clients()
        companion_chroma = chromadb.PersistentClient(
            path=str(MindStores.chroma_dir(SURFACE_COMPANION)),
            settings=Settings(anonymized_telemetry=False),
        )
        assistant_chroma = chromadb.PersistentClient(
            path=str(MindStores.chroma_dir(SURFACE_ASSISTANT)),
            settings=Settings(anonymized_telemetry=False),
        )

        def names(client):
            return {getattr(c, "name", c) for c in client.list_collections()}

        self.assertIn("relationship_life", names(companion_chroma))
        self.assertNotIn("coding_lessons", names(companion_chroma))
        self.assertEqual(companion_chroma.get_collection("relationship_life").count(), 1)
        self.assertNotIn("relationship_life", names(assistant_chroma))
        self.assertEqual(assistant_chroma.get_collection("coding_lessons").count(), 2)
        self.assertEqual(assistant_chroma.get_collection("nlpp_hard_bans").count(), 1)

    def test_bootstrap_is_idempotent(self):
        self._make_legacy_db()
        MemoryUpdater.bootstrap_mind_stores()
        MemoryUpdater.bootstrap_mind_stores()
        with sqlite3.connect(self.db(SURFACE_ASSISTANT)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM chat_logs").fetchone()[0], 2)
        with sqlite3.connect(self.db(SURFACE_COMPANION)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM chat_logs").fetchone()[0], 2)

    def test_fresh_install_creates_both_stores(self):
        MemoryUpdater.bootstrap_mind_stores()
        self.assertTrue(self.db(SURFACE_COMPANION).exists())
        self.assertTrue(self.db(SURFACE_ASSISTANT).exists())
        self.assertFalse((self.mind_root / ".store-migration.lock").exists())
