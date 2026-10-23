"""End-to-end regression: Blossom Assistant must never bleed into Blossom Companion.

Drives the real FastAPI app (models, GPU swaps and the coder mocked) and asserts on
what reaches Haruhi's prompt and what lands in each client's Mind store. These
tests are the tripwire for the bug that "was fixed before and came back".
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fastapi.testclient import TestClient  # noqa: E402

import ChatRouter  # noqa: E402
import MindStores  # noqa: E402
import SemanticMemory  # noqa: E402
from MindStores import SURFACE_ASSISTANT, SURFACE_COMPANION  # noqa: E402
from mind_test_utils import TempMindTestCase  # noqa: E402

CODE_ANSWER = "```python\ndef add(a, b):\n    return a + b\n```"
SESSION_PACK = "USER: refactor docker-compose.yml\nASSISTANT: ```yaml\nservices: {}\n```"


def _rows(db: Path) -> list[tuple[str, str, str]]:
    if not db.exists():
        return []
    with sqlite3.connect(db) as conn:
        return conn.execute(
            "SELECT role, surface, content FROM chat_logs ORDER BY id"
        ).fetchall()


class SurfaceBleedE2ETests(TempMindTestCase):
    def setUp(self):
        super().setUp()
        self.persona_prompts: list[list[dict]] = []

        def fake_persona_reply(messages, **_kwargs):
            self.persona_prompts.append([dict(m) for m in messages])
            return ChatRouter._synthetic_completion("Hmph. Took you long enough.")

        fake_server = MagicMock()
        fake_server.current_role = "persona"
        fake_server.current_ctx = ChatRouter.PERSONA_CTX
        fake_server.coder_available.return_value = True
        self._patches = [
            patch.dict(os.environ, {"BLOSSOM_REQUIRE_CLIENT": "true"}),
            patch.object(ChatRouter, "server_manager", fake_server),
            patch.object(ChatRouter, "_persona_reply", side_effect=fake_persona_reply),
            patch.object(ChatRouter, "_gather_web_context", return_value=""),
            patch.object(ChatRouter, "_should_use_agent_execution", return_value=False),
            patch.object(
                ChatRouter,
                "_get_coding_intel",
                return_value=(CODE_ANSWER, "local_coder", None),
            ),
            patch.object(
                ChatRouter,
                "maybe_attach_voice",
                side_effect=lambda final, **_kw: (final, None),
            ),
            patch.object(ChatRouter, "VOICE_ENABLED", False),
            patch("SemanticMemory.query_memories", return_value=[]),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(ChatRouter.app)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        super().tearDown()

    def chat(self, text: str, *, client: str | None, header: bool = False, **extra):
        body = {"messages": [{"role": "user", "content": text}], **extra}
        headers = {}
        if client and header:
            headers["X-Blossom-Client"] = client
        elif client:
            body["blossom_client"] = client
        return self.client.post("/v1/chat/completions", json=body, headers=headers)

    def companion_prompt_text(self) -> str:
        self.assertTrue(self.persona_prompts, "persona model was never called")
        return "\n".join(str(m.get("content")) for m in self.persona_prompts[-1])

    # --- chat history -------------------------------------------------------

    def test_assistant_coding_turn_never_reaches_companion_prompt(self):
        r = self.chat(
            "fix this python bug in add()",
            client="assistant",
            blossom_session=SESSION_PACK,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["blossom_surface"], SURFACE_ASSISTANT)

        r = self.chat("hey Haruhi, what did you do today?", client="companion")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["blossom_surface"], SURFACE_COMPANION)

        prompt = self.companion_prompt_text()
        for leak in ("def add", "```", "docker", "fix this python bug"):
            self.assertNotIn(leak, prompt)

        companion_rows = _rows(self.db(SURFACE_COMPANION))
        assistant_rows = _rows(self.db(SURFACE_ASSISTANT))
        self.assertTrue(all(s == SURFACE_COMPANION for _, s, _ in companion_rows))
        self.assertFalse(any("def add" in c for _, _, c in companion_rows))
        self.assertTrue(any("def add" in c for _, _, c in assistant_rows))
        self.assertTrue(all(s == SURFACE_ASSISTANT for _, s, _ in assistant_rows))

    def test_header_tag_works_like_body_tag(self):
        r = self.chat("hello there", client="companion", header=True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["blossom_surface"], SURFACE_COMPANION)
        self.assertEqual(len(_rows(self.db(SURFACE_COMPANION))), 2)

    def test_untagged_request_is_rejected(self):
        r = self.chat("hello", client=None)
        self.assertEqual(r.status_code, 400)
        self.assertIn("client", r.json()["detail"].lower())
        self.assertEqual(_rows(self.db(SURFACE_COMPANION)), [])

    def test_untagged_lenient_mode_goes_to_assistant_not_companion(self):
        with patch.dict(os.environ, {"BLOSSOM_REQUIRE_CLIENT": "false"}):
            r = self.chat("fix this python bug", client=None)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["blossom_surface"], SURFACE_ASSISTANT)
        self.assertEqual(_rows(self.db(SURFACE_COMPANION)), [])
        self.assertTrue(_rows(self.db(SURFACE_ASSISTANT)))

    def test_session_pack_is_ignored_for_companion(self):
        r = self.chat(
            "how's it going?", client="companion", blossom_session=SESSION_PACK
        )
        self.assertEqual(r.status_code, 200, r.text)
        prompt = self.companion_prompt_text()
        self.assertNotIn("docker-compose", prompt)
        self.assertNotIn("services: {}", prompt)

    def test_streaming_companion_turn_is_tagged_and_isolated(self):
        self.chat("fix this python bug", client="assistant")
        body = {
            "messages": [{"role": "user", "content": "sing me something"}],
            "blossom_client": "companion",
            "stream": True,
        }
        with self.client.stream("POST", "/v1/chat/completions", json=body) as r:
            self.assertEqual(r.status_code, 200)
            events = [
                json.loads(line[6:])
                for line in r.iter_lines()
                if line.startswith("data: {")
            ]
        thoughts = [e for e in events if e.get("object") == "blossom.thoughts"]
        self.assertEqual(thoughts[-1]["surface"], SURFACE_COMPANION)
        self.assertNotIn("def add", self.companion_prompt_text())
        self.assertFalse(
            any("def add" in c for _, _, c in _rows(self.db(SURFACE_COMPANION)))
        )

    # --- persona ------------------------------------------------------------

    def test_persona_endpoints_are_per_client(self):
        companion = self.client.get(
            "/v1/persona", headers={"X-Blossom-Client": "companion"}
        )
        self.assertEqual(companion.status_code, 200, companion.text)
        r = self.client.put(
            "/v1/persona",
            headers={"X-Blossom-Client": "companion"},
            json={"persona": {"companion_name": "Haruhi Suzumiya"}},
        )
        self.assertEqual(r.status_code, 200, r.text)

        assistant = self.client.get(
            "/v1/persona", headers={"X-Blossom-Client": "assistant"}
        ).json()
        self.assertEqual(assistant["blossom_surface"], SURFACE_ASSISTANT)
        self.assertEqual(assistant["persona"]["companion_name"], "Haruhi Suzumiya")
        self.assertEqual(assistant["persona"]["relationship_stage"], "just met")

        self.client.put(
            "/v1/persona",
            headers={"X-Blossom-Client": "assistant"},
            json={"persona": {"internal_mood_diary": "deep in a refactor"}},
        )
        companion = self.client.get(
            "/v1/persona", headers={"X-Blossom-Client": "companion"}
        ).json()
        self.assertNotEqual(
            companion["persona"]["internal_mood_diary"], "deep in a refactor"
        )

    def test_persona_endpoint_requires_client_tag(self):
        self.assertEqual(self.client.get("/v1/persona").status_code, 400)

    # --- memory endpoints -----------------------------------------------------

    def test_coding_memory_endpoint_refuses_companion(self):
        r = self.client.get(
            "/v1/memory/coding",
            params={"q": "nlpp"},
            headers={"X-Blossom-Client": "companion"},
        )
        self.assertEqual(r.status_code, 409)

    def test_pinned_companion_router_rejects_assistant(self):
        with patch.dict(os.environ, {"BLOSSOM_SURFACE": "companion"}):
            r = self.chat("fix this python bug", client="assistant")
            self.assertEqual(r.status_code, 409)
            r = self.client.get("/v1/memory/coding", params={"q": "x"})
            self.assertEqual(r.status_code, 409)


class CollectionHomeTests(TempMindTestCase):
    def test_coding_collections_unreachable_from_companion(self):
        with MindStores.surface_scope(SURFACE_COMPANION):
            self.assertIsNone(SemanticMemory._get_collection(SemanticMemory.COLLECTION_CODING))
            self.assertIsNone(
                SemanticMemory._get_collection(SemanticMemory.COLLECTION_HARD_BANS)
            )
            self.assertEqual(
                SemanticMemory.query_memories("x", collection=SemanticMemory.COLLECTION_CODING),
                [],
            )

    def test_life_collections_unreachable_from_assistant(self):
        with MindStores.surface_scope(SURFACE_ASSISTANT):
            self.assertIsNone(SemanticMemory._get_collection(SemanticMemory.COLLECTION_LIFE))
            self.assertIsNone(
                SemanticMemory._get_collection(SemanticMemory.COLLECTION_LANGUAGE)
            )
            self.assertEqual(
                SemanticMemory.add_memory("secret", collection=SemanticMemory.COLLECTION_LIFE),
                "",
            )

    def test_web_knowledge_is_split_per_client(self):
        self.assertEqual(
            SemanticMemory.store_surface_for(SemanticMemory.COLLECTION_WEB, SURFACE_COMPANION),
            SURFACE_COMPANION,
        )
        self.assertEqual(
            SemanticMemory.store_surface_for(SemanticMemory.COLLECTION_WEB, SURFACE_ASSISTANT),
            SURFACE_ASSISTANT,
        )
        self.assertIsNone(SemanticMemory.store_surface_for(SemanticMemory.COLLECTION_WEB))
        self.assertNotEqual(
            MindStores.chroma_dir(SURFACE_COMPANION), MindStores.chroma_dir(SURFACE_ASSISTANT)
        )
