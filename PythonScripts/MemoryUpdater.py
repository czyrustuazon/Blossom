import json
import logging
import os
import sqlite3
from pathlib import Path

import requests
from dotenv import load_dotenv

# Project root = parent of PythonScripts/, so paths stay valid if the project folder moves.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

# Load .env before any os.getenv reads (PythonScripts/.env, then project-root .env).
load_dotenv(SCRIPT_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

MIND_DIR = PROJECT_ROOT / "Mind"
DB_PATH = MIND_DIR / "CompanionMind.db"
MODELS_DIR = PROJECT_ROOT / "Brains" / "models"
RUNTIME_DIR = PROJECT_ROOT / "Brains" / "runtime"
LLAMA_SERVER_EXE = RUNTIME_DIR / "llama-server.exe"
CONVERSATIONAL_MODEL = MODELS_DIR / "conversational" / "Qwen3-8B-Q4_K_M.gguf"
LLAMA_SERVER_URL = "http://127.0.0.1:11434"
CHAT_COMPLETIONS_URL = f"{LLAMA_SERVER_URL}/v1/chat/completions"

# Run persona self-reflection after this many assistant replies (override with env).
REFLECTION_EVERY_N_TURNS = max(1, int(os.getenv("REFLECTION_EVERY_N_TURNS", "10")))
REFLECTION_STATE_KEY = "last_reflection_assistant_count"

DEFAULT_PROFILE = {
    "relationship_stage": "just met",
    "internal_mood_diary": "curious and warm",
    "perceived_user_traits": [],
    "linguistic_quirks": ["playful teasing", "clear technical explanations"],
}

logger = logging.getLogger(__name__)


def ensure_mind_db() -> Path:
    """Create Mind/ and required tables if missing. Never wipe an existing DB."""
    MIND_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS evolution_matrix (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        # semantic_memories now live in ChromaDB (Mind/chromadb). Keep legacy table
        # if it already exists so migrate_sqlite_semantic_memories can copy rows.
        cursor.execute("SELECT value FROM evolution_matrix WHERE key='profile'")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO evolution_matrix (key, value) VALUES (?, ?)",
                ("profile", json.dumps(DEFAULT_PROFILE)),
            )
        cursor.execute(
            "SELECT value FROM evolution_matrix WHERE key=?",
            (REFLECTION_STATE_KEY,),
        )
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO evolution_matrix (key, value) VALUES (?, ?)",
                (REFLECTION_STATE_KEY, "0"),
            )
        conn.commit()
    finally:
        conn.close()

    return DB_PATH


def _assistant_text_from_response(response_json: dict) -> str:
    message = response_json["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    if content:
        return content
    # Qwen3 sometimes returns only reasoning_content when content is empty
    return (message.get("reasoning_content") or "").strip()


def chat_completion(messages, temperature=0.7, timeout=120.0) -> str:
    payload = {
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    response = requests.post(CHAT_COMPLETIONS_URL, json=payload, timeout=timeout)
    response.raise_for_status()
    return _assistant_text_from_response(response.json())


ensure_mind_db()
try:
    from SemanticMemory import migrate_sqlite_semantic_memories

    migrate_sqlite_semantic_memories()
except Exception as exc:
    logger.warning("Semantic memory migration skipped: %s", exc)


class CompanionEngine:
    def __init__(
        self,
        base_url=CHAT_COMPLETIONS_URL,
        reflection_every_n_turns: int = REFLECTION_EVERY_N_TURNS,
    ):
        self.base_url = base_url
        self.db_path = str(ensure_mind_db())
        self.reflection_every_n_turns = max(1, int(reflection_every_n_turns))
        self.static_core = (
            "You are a local AI companion: warm, sharp, and a little teasing when it fits. "
            "Sound like a real person texting a friend who codes — not a mascot, not a customer-support bot.\n"
            "Style rules (strict):\n"
            "- Be specific to THIS message. Never reuse stock bits (holy grail, sacred text, passport, "
            "Russian nesting doll, detective game, masterpiece, P.S. gimmicks).\n"
            "- Prefer plain prose over bullet sermons unless a short list genuinely helps.\n"
            "- At most one emoji, and only if it feels natural. Zero is fine.\n"
            "- No theatrical openings ('Ah, *filename*—…'). Just start helping.\n"
            "- If file contents/context are missing, say that once and ask for the missing piece — "
            "do not invent a generic tutorial instead.\n"
            "- Keep wit light; never let jokes replace the actual fix."
        )

    def _get_profile(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM evolution_matrix WHERE key='profile'")
        profile_data = json.loads(cursor.fetchone()[0])
        conn.close()
        return profile_data

    def _get_short_term_context(self, limit=12):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content FROM chat_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    def _assistant_turn_count(self) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM chat_logs WHERE role='assistant'")
        count = cursor.fetchone()[0]
        conn.close()
        return int(count)

    def _get_last_reflection_assistant_count(self) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM evolution_matrix WHERE key=?",
            (REFLECTION_STATE_KEY,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return 0
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return 0

    def _set_last_reflection_assistant_count(self, count: int) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO evolution_matrix (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (REFLECTION_STATE_KEY, str(count)),
        )
        conn.commit()
        conn.close()

    def _log_message(self, role, content):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chat_logs (role, content) VALUES (?, ?)",
            (role, content),
        )
        conn.commit()
        conn.close()
        if role == "assistant":
            self.maybe_run_self_reflection()

    def build_persona_system_prompt(self, user_text: str | None = None) -> str:
        profile = self._get_profile()
        quirks = profile.get("linguistic_quirks") or []
        if isinstance(quirks, list):
            quirk_text = ", ".join(str(q) for q in quirks) if quirks else "natural conversational tone"
        else:
            quirk_text = str(quirks)
        traits = profile.get("perceived_user_traits") or []
        if isinstance(traits, list):
            traits_text = ", ".join(str(t) for t in traits) if traits else "still learning"
        else:
            traits_text = str(traits)

        prompt = (
            f"{self.static_core}\n\n"
            f"[CURRENT EVOLUTION STATE]\n"
            f"- Relationship Status with User: {profile.get('relationship_stage', 'unknown')}\n"
            f"- Your Current Internal Mood: {profile.get('internal_mood_diary', 'neutral')}\n"
            f"- User Observations: {traits_text}\n"
            f"- Tone notes: {quirk_text}. Keep personality, but never become repetitive or plastic."
        )
        if user_text:
            try:
                from SemanticMemory import (
                    COLLECTION_LIFE,
                    format_memories_for_prompt,
                    query_memories,
                )

                memory_block = format_memories_for_prompt(
                    query_memories(user_text, collection=COLLECTION_LIFE)
                )
                if memory_block:
                    prompt = f"{prompt}\n\n{memory_block}"
            except Exception as exc:
                logger.warning("Semantic memory retrieval skipped: %s", exc)
        return prompt

    def build_chat_messages(self, user_text: str, history_limit: int = 12) -> list:
        """Log the user turn and build persona + memories + recent history."""
        self._log_message("user", user_text)
        messages = [
            {"role": "system", "content": self.build_persona_system_prompt(user_text)}
        ]
        messages.extend(self._get_short_term_context(limit=history_limit))
        return messages

    def generate_reply(self, user_text: str):
        messages = self.build_chat_messages(user_text)
        ai_text = chat_completion(messages, temperature=0.82)
        self._log_message("assistant", ai_text)
        return ai_text

    def maybe_run_self_reflection(self, force: bool = False):
        """Auto-run reflection every N assistant turns (CLI, router, etc.)."""
        assistant_count = self._assistant_turn_count()
        last_count = self._get_last_reflection_assistant_count()
        due = force or (assistant_count - last_count) >= self.reflection_every_n_turns
        if not due:
            return None

        logger.info(
            "Self-reflection due (assistant turns=%s, last=%s, every=%s).",
            assistant_count,
            last_count,
            self.reflection_every_n_turns,
        )
        updated = self.execute_self_reflection()
        # Advance the marker even on failure so a bad parse doesn't retry every message.
        self._set_last_reflection_assistant_count(assistant_count)
        return updated

    def execute_self_reflection(self):
        """Evolve persona metrics from recent chat."""
        profile = self._get_profile()
        history = self._get_short_term_context(limit=20)
        history_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in history
        )

        reflection_prompt = (
            "Analyze the following recent chat script between you and your creator. "
            "Based strictly on this script, update your internal persona metrics.\n\n"
            f"CURRENT METRICS:\n{json.dumps(profile, indent=2)}\n\n"
            f"CHAT LOGS:\n{history_text}\n\n"
            "Output a valid, raw JSON block matching the structure above exactly. "
            "Adjust your 'internal_mood_diary' to reflect how the conversation would leave you feeling. "
            "Update 'perceived_user_traits' if you noticed new skills, patterns, or behaviors. "
            "Slightly shift your 'relationship_stage' if the emotional distance or closeness has evolved. "
            "Do not include markdown or text wrapping outside the raw JSON object."
        )

        try:
            raw_json_str = chat_completion(
                [{"role": "user", "content": reflection_prompt}],
                temperature=0.2,
            )
            cleaned = raw_json_str.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].strip()
            updated_profile = json.loads(cleaned)

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE evolution_matrix SET value=? WHERE key='profile'",
                (json.dumps(updated_profile),),
            )
            conn.commit()
            conn.close()
            logger.info("Companion self-reflection completed. Character profile evolved.")
            return updated_profile
        except Exception as e:
            logger.error("Reflection failed or parsing error: %s", e)
            return None


def run_chat_cli():
    """Interactive companion chat. Requires llama-server to already be running."""
    logging.basicConfig(level=logging.INFO, format="[Blossom]: %(message)s")
    engine = CompanionEngine()
    print("Companion ready. Type your message (or 'exit' / 'quit' to stop).")
    print(
        f"Self-reflection runs automatically every {engine.reflection_every_n_turns} replies."
    )
    print("Commands: /reflect  — force self-reflection now")
    while True:
        try:
            user_text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not user_text:
            continue
        if user_text.lower() in {"exit", "quit"}:
            print("Bye.")
            break
        if user_text.lower() == "/reflect":
            engine.maybe_run_self_reflection(force=True)
            continue
        reply = engine.generate_reply(user_text)
        print(f"\nCompanion: {reply}")


if __name__ == "__main__":
    run_chat_cli()
