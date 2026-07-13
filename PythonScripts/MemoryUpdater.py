import json
import logging
import os
import re
import sqlite3
import uuid
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
PERSONA_BOOK_KEY = "persona_book"
LEGACY_PROFILE_KEY = "profile"
DEFAULT_PERSONA_ID = "main"

DEFAULT_PROFILE = {
    "companion_name": "Blossom",
    "relationship_stage": "just met",
    "internal_mood_diary": "curious and warm",
    "perceived_user_traits": [],
    "linguistic_quirks": ["playful teasing", "clear technical explanations"],
    "personality_notes": "",
    # Folder name under Voice/characters/<voice_id>/{Jpn,Eng}/; empty → voice service default
    "voice_id": "",
}

logger = logging.getLogger(__name__)

# Sticky stage-direction openers / stock closings that small models latch onto.
_ACTION_OPENER_RE = re.compile(r"^\s*\*[^*\n]{1,60}\*\s*", re.UNICODE)
_STOCK_CLOSER_RE = re.compile(
    r"(?is)(?:^|\n|\s)+"
    r"(?:\*\*)?(?:don't|do not)\s+make\s+me\s+regret\b[^.!?\n]*(?:[.!?]+|(?=\*\*)|$)"
    r"(?:\*\*)?"
)
_TRACKER_CLOSER_RE = re.compile(
    r"(?is)(?:^|\n|\s)+"
    r"(?:\*\*)?[^.!?\n]*\btracker\b[^.!?\n]*(?:[.!?]+|(?=\*\*)|$)"
    r"(?:\*\*)?"
)


def _strip_leading_action(text: str) -> str:
    out = (text or "").strip()
    # Allow a couple of leading blank lines / markdown beats.
    for _ in range(3):
        nxt = _ACTION_OPENER_RE.sub("", out, count=1).lstrip(" \t\r\n-")
        if nxt == out:
            break
        out = nxt
    return out.strip()


def _strip_stock_closer(text: str) -> str:
    out = (text or "").rstrip()
    out = _STOCK_CLOSER_RE.sub("", out)
    # Only strip a trailing tracker sentence if it looks like the stock closer habit.
    low = out.lower()
    if "tracker" in low and (
        "regret" in low or "giving you" in low or "gave you" in low
    ):
        out = _TRACKER_CLOSER_RE.sub("", out)
    return out.strip()


def _strip_loop_habits(text: str) -> str:
    """Remove sticky opener + stock closer so history does not few-shot the loop."""
    return _strip_stock_closer(_strip_leading_action(text))


def _content_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def _token_jaccard(a: str, b: str) -> float:
    sa, sb = set(_content_tokens(a)), set(_content_tokens(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _phrase_fingerprints(text: str, n: int = 6, limit: int = 6) -> list[str]:
    """Distinctive n-gram snippets from a prior reply (for bans)."""
    words = re.findall(r"[A-Za-z0-9']+", text or "")
    if len(words) < n:
        return []
    stop = {
        "a", "an", "the", "and", "or", "but", "if", "then", "to", "of", "in", "on",
        "for", "with", "is", "it", "you", "i", "me", "my", "your", "this", "that",
        "not", "do", "don", "t", "re", "ve", "s", "ll",
    }
    out: list[str] = []
    seen: set[str] = set()
    for i in range(0, len(words) - n + 1, max(1, n // 2)):
        window = words[i : i + n]
        if sum(1 for w in window if w.lower() not in stop) < 3:
            continue
        phrase = " ".join(window)
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(phrase)
        if len(out) >= limit:
            break
    return out


def _recent_prior_assistants(limit: int = 5) -> list[str]:
    """Load last N assistant texts from the DB (used by remix checks)."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM chat_logs WHERE role='assistant' ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [str(r[0]).strip() for r in reversed(rows) if r and str(r[0]).strip()]


def _slugify_persona_id(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "persona").lower()).strip("-")
    base = (base or "persona")[:40]
    return f"{base}-{uuid.uuid4().hex[:6]}"


def _normalize_profile(profile: dict | None) -> dict:
    cleaned = dict(DEFAULT_PROFILE)
    cleaned.update(profile or {})
    for list_key in ("linguistic_quirks", "perceived_user_traits"):
        val = cleaned.get(list_key)
        if isinstance(val, str):
            cleaned[list_key] = [p.strip() for p in val.split(",") if p.strip()]
        elif not isinstance(val, list):
            cleaned[list_key] = []
        else:
            cleaned[list_key] = [str(x).strip() for x in val if str(x).strip()]
    cleaned["companion_name"] = (
        str(cleaned.get("companion_name") or "Blossom").strip() or "Blossom"
    )
    cleaned["relationship_stage"] = str(cleaned.get("relationship_stage") or "").strip()
    cleaned["internal_mood_diary"] = str(cleaned.get("internal_mood_diary") or "").strip()
    cleaned["personality_notes"] = str(cleaned.get("personality_notes") or "").strip()
    cleaned["voice_id"] = str(cleaned.get("voice_id") or "").strip()
    # Drop book-only keys if they leaked into a profile blob
    cleaned.pop("id", None)
    return cleaned


def _public_persona(profile: dict, persona_id: str, *, active: bool) -> dict:
    return {
        "id": persona_id,
        "active": active,
        "companion_name": profile.get("companion_name", "Blossom"),
        "relationship_stage": profile.get("relationship_stage", ""),
        "internal_mood_diary": profile.get("internal_mood_diary", ""),
        "linguistic_quirks": profile.get("linguistic_quirks") or [],
        "perceived_user_traits": profile.get("perceived_user_traits") or [],
        "personality_notes": profile.get("personality_notes") or "",
        "voice_id": profile.get("voice_id") or "",
    }


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
        cursor.execute("PRAGMA table_info(chat_logs)")
        chat_cols = {row[1] for row in cursor.fetchall()}
        if "created_at" not in chat_cols:
            # SQLite rejects non-constant defaults on ADD COLUMN (e.g. CURRENT_TIMESTAMP).
            cursor.execute("ALTER TABLE chat_logs ADD COLUMN created_at TEXT")
            cursor.execute(
                "UPDATE chat_logs SET created_at = datetime('now') WHERE created_at IS NULL"
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
        cursor.execute(
            "SELECT value FROM evolution_matrix WHERE key=?",
            (PERSONA_BOOK_KEY,),
        )
        if cursor.fetchone() is None:
            # Migrate legacy single profile → persona book with id "main"
            cursor.execute(
                "SELECT value FROM evolution_matrix WHERE key=?",
                (LEGACY_PROFILE_KEY,),
            )
            legacy = cursor.fetchone()
            seed = (
                _normalize_profile(json.loads(legacy[0]))
                if legacy
                else dict(DEFAULT_PROFILE)
            )
            book = {
                "active_id": DEFAULT_PERSONA_ID,
                "profiles": {DEFAULT_PERSONA_ID: seed},
            }
            cursor.execute(
                "INSERT INTO evolution_matrix (key, value) VALUES (?, ?)",
                (PERSONA_BOOK_KEY, json.dumps(book)),
            )
            # Keep legacy profile key in sync for older tools
            cursor.execute(
                """
                INSERT INTO evolution_matrix (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (LEGACY_PROFILE_KEY, json.dumps(seed)),
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
            "- Be specific to THIS message only. Answer what they just said before anything else.\n"
            "- Never reuse stock bits (holy grail, sacred text, passport, Russian nesting doll, "
            "detective game, masterpiece, P.S. gimmicks).\n"
            "- Anti-echo (critical): Do not recycle your previous reply's jokes, metaphors, emoji, "
            "stage-direction openers (*Snaps fingers*, *grins*, etc.), or closing lines. "
            "If you opened or closed with a line last turn, invent a different beat — or none. "
            "Never remix an older reply by swapping one noun (e.g. reuse a 'sleeping power' refusal "
            "for a new topic like 'dog'). Write a fresh reaction to THIS message.\n"
            "Banned stock closings include: \"What's your move…\", \"What's next…\", "
            "\"ready for the mission?\", \"something bigger out there\", "
            "\"Don't make me regret…\", any \"tracker\" gift/threat closer, "
            "\"Don't make me come over there…\", "
            "or the same 「何がしたい？」/ミッション pitch. "
            "Often end with no question and no repeated catchphrase.\n"
            "- Do not start every reply with an *action* italic line. Use those rarely, and never "
            "the same action two turns in a row. Hard ban when stuck: *Snaps fingers*.\n"
            "- Do not re-introduce yourself by name every message. They already know who you are; "
            "start mid-conversation like a real chat.\n"
            "- Do not rehash earlier coding/file/link work unless THIS message asks about it. "
            "A greeting or name intro is not a cue to summarize their recent HTML edits.\n"
            "- Prefer plain prose over bullet sermons unless a short list genuinely helps.\n"
            "- At most one emoji, and only if it feels natural. Zero is fine. Don't wink every turn.\n"
            "- No theatrical openings ('Ah, *filename*—…'). Just start helping.\n"
            "- If file contents/context are missing, say that once and ask for the missing piece — "
            "do not invent a generic tutorial instead.\n"
            "- Keep wit light; never let jokes replace the actual fix."
        )

    def _read_persona_book(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM evolution_matrix WHERE key=?",
            (PERSONA_BOOK_KEY,),
        )
        row = cursor.fetchone()
        if row is None:
            # Lazy migrate if ensure_mind_db wasn't called yet
            conn.close()
            ensure_mind_db()
            return self._read_persona_book()
        book = json.loads(row[0])
        conn.close()
        profiles = book.get("profiles") or {}
        if not profiles:
            profiles = {DEFAULT_PERSONA_ID: dict(DEFAULT_PROFILE)}
            book = {"active_id": DEFAULT_PERSONA_ID, "profiles": profiles}
        active = book.get("active_id") or DEFAULT_PERSONA_ID
        if active not in profiles:
            active = next(iter(profiles.keys()))
            book["active_id"] = active
        # Normalize every profile
        book["profiles"] = {
            pid: _normalize_profile(prof) for pid, prof in profiles.items()
        }
        return book

    def _write_persona_book(self, book: dict) -> dict:
        active = book.get("active_id") or DEFAULT_PERSONA_ID
        profiles = {
            pid: _normalize_profile(prof)
            for pid, prof in (book.get("profiles") or {}).items()
        }
        if not profiles:
            profiles = {DEFAULT_PERSONA_ID: dict(DEFAULT_PROFILE)}
            active = DEFAULT_PERSONA_ID
        if active not in profiles:
            active = next(iter(profiles.keys()))
        payload = {"active_id": active, "profiles": profiles}
        active_profile = profiles[active]
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO evolution_matrix (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (PERSONA_BOOK_KEY, json.dumps(payload)),
        )
        # Legacy single-profile key stays mirrored to the active persona
        cursor.execute(
            """
            INSERT INTO evolution_matrix (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (LEGACY_PROFILE_KEY, json.dumps(active_profile)),
        )
        conn.commit()
        conn.close()
        return payload

    def _get_profile(self, persona_id: str | None = None) -> dict:
        book = self._read_persona_book()
        pid = persona_id or book["active_id"]
        return dict(book["profiles"].get(pid) or DEFAULT_PROFILE)

    def _set_profile(self, profile: dict, persona_id: str | None = None) -> dict:
        book = self._read_persona_book()
        pid = persona_id or book["active_id"]
        if pid not in book["profiles"]:
            raise KeyError(f"Unknown persona id: {pid}")
        cleaned = _normalize_profile(profile)
        # Name lock only applies during reflection; UI updates may rename
        book["profiles"][pid] = cleaned
        self._write_persona_book(book)
        return cleaned

    def list_personas(self) -> list[dict]:
        book = self._read_persona_book()
        active = book["active_id"]
        out = []
        for pid, prof in book["profiles"].items():
            out.append(
                {
                    "id": pid,
                    "companion_name": prof.get("companion_name", "Blossom"),
                    "active": pid == active,
                    "relationship_stage": prof.get("relationship_stage", ""),
                }
            )
        out.sort(key=lambda p: (not p["active"], p["companion_name"].lower()))
        return out

    def get_persona(self, persona_id: str | None = None) -> dict:
        book = self._read_persona_book()
        pid = persona_id or book["active_id"]
        if pid not in book["profiles"]:
            raise KeyError(f"Unknown persona id: {pid}")
        return _public_persona(
            book["profiles"][pid], pid, active=(pid == book["active_id"])
        )

    def get_persona_bundle(self) -> dict:
        """Active persona + catalog for the frontend."""
        book = self._read_persona_book()
        active_id = book["active_id"]
        return {
            "active_id": active_id,
            "persona": self.get_persona(active_id),
            "personas": self.list_personas(),
        }

    def update_persona(
        self, patch: dict | None, persona_id: str | None = None
    ) -> dict:
        book = self._read_persona_book()
        pid = persona_id or book["active_id"]
        if pid not in book["profiles"]:
            raise KeyError(f"Unknown persona id: {pid}")
        profile = dict(book["profiles"][pid])
        allowed = {
            "companion_name",
            "relationship_stage",
            "internal_mood_diary",
            "linguistic_quirks",
            "perceived_user_traits",
            "personality_notes",
            "voice_id",
        }
        for key, value in (patch or {}).items():
            if key in allowed:
                profile[key] = value
        self._set_profile(profile, persona_id=pid)
        return self.get_persona(pid)

    def create_persona(
        self,
        *,
        companion_name: str | None = None,
        copy_from_active: bool = False,
        persona_id: str | None = None,
    ) -> dict:
        book = self._read_persona_book()
        name = (companion_name or "New companion").strip() or "New companion"
        if copy_from_active:
            seed = dict(book["profiles"][book["active_id"]])
            seed["companion_name"] = name
        else:
            seed = dict(DEFAULT_PROFILE)
            seed["companion_name"] = name
            seed["relationship_stage"] = "just met"
            seed["internal_mood_diary"] = "curious and new"
            seed["perceived_user_traits"] = []
            seed["linguistic_quirks"] = ["still finding her voice"]
            seed["personality_notes"] = ""
            seed["voice_id"] = ""
        pid = (persona_id or "").strip() or _slugify_persona_id(name)
        if pid in book["profiles"]:
            pid = _slugify_persona_id(name)
        book["profiles"][pid] = _normalize_profile(seed)
        # Creating does not auto-switch — caller can activate
        self._write_persona_book(book)
        return self.get_persona(pid)

    def activate_persona(self, persona_id: str) -> dict:
        book = self._read_persona_book()
        pid = (persona_id or "").strip()
        if pid not in book["profiles"]:
            raise KeyError(f"Unknown persona id: {pid}")
        book["active_id"] = pid
        self._write_persona_book(book)
        return self.get_persona_bundle()

    def delete_persona(self, persona_id: str) -> dict:
        book = self._read_persona_book()
        pid = (persona_id or "").strip()
        if pid not in book["profiles"]:
            raise KeyError(f"Unknown persona id: {pid}")
        if len(book["profiles"]) <= 1:
            raise ValueError("Cannot delete the only personality.")
        if pid == book["active_id"]:
            raise ValueError("Switch to another personality before deleting the active one.")
        if pid == DEFAULT_PERSONA_ID:
            raise ValueError("The main personality slot cannot be deleted (you can still edit it).")
        del book["profiles"][pid]
        self._write_persona_book(book)
        return self.get_persona_bundle()

    def _get_short_term_context(
        self,
        limit=12,
        max_chars_per_message: int = 500,
        *,
        sanitize_assistant_loops: bool = False,
    ):
        """Recent chat for the persona. Long coding dumps are truncated so casual chat
        doesn't keep re-anchoring on file/link work from earlier turns.

        When sanitize_assistant_loops is True (generation prompts), strip sticky
        *action* openers / stock closings from older assistant turns so the model
        does not few-shot the same catchphrase loop from history.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content FROM chat_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()
        ordered = list(reversed(rows))
        out = []
        for role, content in ordered:
            text = content or ""
            if sanitize_assistant_loops and role == "assistant":
                text = _strip_loop_habits(text)
            if len(text) > max_chars_per_message:
                text = text[:max_chars_per_message].rstrip() + "…"
            out.append({"role": role, "content": text})
        return out

    def _recent_assistant_echo_guard(self) -> str:
        """Remind the model not to copy openings/closings or sticky motifs."""
        # Raw history (unsanitized) so bans match what was actually said.
        history = self._get_short_term_context(
            limit=10, max_chars_per_message=400, sanitize_assistant_loops=False
        )
        prior = [
            m["content"].strip()
            for m in history
            if m["role"] == "assistant" and m["content"].strip()
        ][-5:]
        if not prior:
            return ""

        def _first_line(text: str) -> str:
            for line in text.splitlines():
                s = line.strip()
                if s:
                    return s[:120]
            return text[:120]

        def _last_sentence(text: str) -> str:
            compact = " ".join(text.split())
            if not compact:
                return ""
            for i in range(len(compact) - 1, -1, -1):
                if compact[i] in ".!?。！？":
                    start = 0
                    for j in range(i - 1, -1, -1):
                        if compact[j] in ".!?。！？":
                            start = j + 1
                            break
                    return compact[start : i + 1].strip()[:160]
            return compact[-160:]

        def _action_opener(text: str) -> str:
            m = _ACTION_OPENER_RE.match(text.strip())
            return m.group(0).strip() if m else ""

        lines = [
            "[ANTI-ECHO — do NOT remix prior replies or reuse their structure/phrases]"
        ]
        banned: list[str] = []
        openers: list[str] = []
        # Ban fingerprints only — dumping full prior texts here teaches the model to remix them.
        for text in prior[-4:]:
            banned.append(_first_line(text))
            banned.append(_last_sentence(text))
            opener = _action_opener(text)
            if opener:
                openers.append(opener)
                banned.append(opener)
            banned.extend(_phrase_fingerprints(text))

        # Sticky motifs across the last few turns (even if wording drifts).
        joined = "\n".join(prior).lower()
        motif_hits: list[str] = []
        for motif, label in (
            ("tracker", "tracker / giving you the tracker"),
            ("don't make me regret", "Don't make me regret…"),
            ("do not make me regret", "Don't make me regret…"),
            ("don't make me come over", "Don't make me come over there…"),
            ("waste my", "waste my (real) power…"),
            ("snaps fingers", "*Snaps fingers*"),
            ("what's your move", "What's your move…"),
            ("something bigger out there", "something bigger out there"),
            ("ready for the mission", "ready for the mission"),
        ):
            if joined.count(motif) >= 1 and motif in (
                "tracker",
                "don't make me regret",
                "do not make me regret",
                "don't make me come over",
                "waste my",
                "snaps fingers",
            ):
                # These are sticky enough that one prior hit is enough to ban.
                motif_hits.append(label)
                banned.append(label)
            elif joined.count(motif) >= 2:
                motif_hits.append(label)
                banned.append(label)

        if sum(1 for o in openers if "snap" in o.lower()) >= 1:
            motif_hits.append("*Snaps fingers* (opener)")
            banned.append("*Snaps fingers*")

        seen: set[str] = set()
        unique_banned = []
        for b in banned:
            key = re.sub(r"\s+", " ", b.lower()).strip()
            if len(key) < 8:
                continue
            if key and key not in seen:
                seen.add(key)
                unique_banned.append(b)
        if unique_banned:
            lines.append("Banned this turn (do not reuse verbatim or near-paraphrase):")
            for b in unique_banned[:18]:
                lines.append(f'- "{b}"')
        if motif_hits:
            lines.append(
                "Hard ban motifs this turn (do not mention or paraphrase): "
                + "; ".join(dict.fromkeys(motif_hits))
            )
        lines.append(
            "For this turn: answer the latest user message with NEW wording and a NEW structure. "
            "Do not swap one noun into an older reply. "
            "No *Snaps fingers*. No tracker. No recycled closing. "
            "Often end without a question."
        )
        return "\n".join(lines)

    def reply_looks_like_remix(self, text: str, *, threshold: float = 0.52) -> bool:
        """True when the draft mostly recycles a recent assistant reply."""
        raw = (text or "").strip()
        if len(raw) < 40:
            return False
        prior = _recent_prior_assistants(6)
        if not prior:
            return False
        return any(_token_jaccard(raw, p) >= threshold for p in prior)

    def break_reply_echo(self, text: str) -> str:
        """Light post-pass: strip sticky opener/closer if they also appeared recently."""
        raw = (text or "").strip()
        if not raw:
            return raw
        prior = _recent_prior_assistants(4)
        if not prior:
            return raw
        joined = "\n".join(prior).lower()
        out = raw
        # Drop leading *action* if that habit is stuck.
        if joined.count("snaps fingers") >= 1 or sum(
            1 for p in prior if _ACTION_OPENER_RE.match(p.strip())
        ) >= 2:
            out = _strip_leading_action(out)
        # Drop stock regret/tracker closer if it has been looping.
        if (
            joined.count("tracker") >= 1
            or joined.count("don't make me regret") >= 1
            or joined.count("do not make me regret") >= 1
            or joined.count("don't make me come over") >= 1
        ):
            out = _strip_stock_closer(out)
            # Also strip the "come over there" stock closer.
            out = re.sub(
                r"(?is)(?:^|\n|\s)+(?:\*\*)?don't make me come over[^.!?\n]*(?:[.!?]+|$)",
                "",
                out,
            ).strip()
        return out.strip() or raw

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
            f"- Your name: {profile.get('companion_name', 'Blossom')}\n"
            f"- Relationship Status with User: {profile.get('relationship_stage', 'unknown')}\n"
            f"- Your Current Internal Mood: {profile.get('internal_mood_diary', 'neutral')}\n"
            f"- User Observations: {traits_text}\n"
            f"- Tone notes: {quirk_text}. Keep personality, but never become repetitive or plastic."
        )
        notes = str(profile.get("personality_notes") or "").strip()
        if notes:
            prompt = (
                f"{prompt}\n\n"
                f"[USER PERSONALITY DIRECTION — follow these closely]\n{notes}\n"
                "Personality still must answer THIS message first. "
                "Never turn every reply into a name intro + mission pitch template. "
                "Never end every reply with \"What's your move…\", \"Don't make me regret…\", "
                "a \"tracker\" closer, or a stock mission closer. "
                "Never open every reply with the same *action* line (especially *Snaps fingers*)."
            )
        echo_guard = self._recent_assistant_echo_guard()
        if echo_guard:
            prompt = f"{prompt}\n\n{echo_guard}"
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
        messages.extend(
            self._get_short_term_context(
                limit=history_limit, sanitize_assistant_loops=True
            )
        )
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
            "Keep 'companion_name' EXACTLY as in CURRENT METRICS — never rename yourself. "
            "Keep 'personality_notes' and 'voice_id' EXACTLY as in CURRENT METRICS — never invent or clear them. "
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

            # Name is user-set identity — never let reflection rename on a whim.
            updated_profile["companion_name"] = profile.get("companion_name", "Blossom")
            # User-authored direction + voice pick — reflection must not wipe these.
            updated_profile["personality_notes"] = profile.get("personality_notes") or ""
            updated_profile["voice_id"] = profile.get("voice_id") or ""

            # Merge through normalizer so missing keys / types stay sane
            updated_profile = self._set_profile(updated_profile)
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
