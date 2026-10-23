import logging
import sqlite3

import MindStores
from MemoryUpdater import (
    CHAT_COMPLETIONS_URL,
    chat_completion,
    ensure_mind_db,
)
from MindStores import SURFACE_ASSISTANT, SURFACE_COMPANION, SURFACES, surface_scope
from SemanticMemory import COLLECTION_LIFE, add_memory

logging.basicConfig(level=logging.INFO, format="[Blossom Compactor]: %(message)s")
logger = logging.getLogger(__name__)


def _db(surface: str) -> str:
    return str(MindStores.db_path(surface))


def _stale_history_for_persona(persona_id: str, keep_last_n: int, surface: str):
    conn = sqlite3.connect(_db(surface), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) as total FROM chat_logs
        WHERE persona_id=? AND surface=?
        """,
        (persona_id, surface),
    )
    total_rows = cursor.fetchone()["total"]

    if total_rows <= keep_last_n:
        conn.close()
        return []

    rows_to_process = total_rows - keep_last_n
    cursor.execute(
        """
        SELECT id, role, content, created_at
        FROM chat_logs
        WHERE persona_id=? AND surface=?
        ORDER BY id ASC
        LIMIT ?
        """,
        (persona_id, surface, rows_to_process),
    )
    stale_rows = cursor.fetchall()
    conn.close()
    return stale_rows


def _purge_stale_rows(persona_id: str, surface: str, keep_last_n: int) -> bool:
    """Drop old rows for a surface without writing relationship_life memories."""
    stale_rows = _stale_history_for_persona(persona_id, keep_last_n, surface)
    if not stale_rows:
        return False
    max_stale_id = stale_rows[-1]["id"]
    with sqlite3.connect(_db(surface), timeout=30.0) as write_conn:
        write_conn.execute("PRAGMA journal_mode=WAL;")
        write_conn.execute(
            "DELETE FROM chat_logs WHERE persona_id=? AND surface=? AND id <= ?",
            (persona_id, surface, max_stale_id),
        )
    logger.info(
        "Purged %s stale %s-surface rows for persona %s (no life-memory archive).",
        len(stale_rows),
        surface,
        persona_id,
    )
    return True


def _compact_persona_history(persona_id: str, keep_last_n: int) -> bool:
    """Archive Companion history into Companion's relationship_life; never Assistant."""
    surface = SURFACE_COMPANION
    stale_rows = _stale_history_for_persona(persona_id, keep_last_n, surface)
    if not stale_rows:
        return False

    max_stale_id = stale_rows[-1]["id"]
    transcript_segments = []
    for row in stale_rows:
        speaker = "User" if row["role"] == "user" else "Companion"
        if row["created_at"]:
            transcript_segments.append(
                f"[{row['created_at']}] {speaker}: {row['content']}"
            )
        else:
            transcript_segments.append(f"{speaker}: {row['content']}")
    raw_transcript_block = "\n".join(transcript_segments)

    compaction_system_instruction = (
        "You are an internal semantic memory compiler. Analyze the raw chat history log "
        "and convert it into a single, high-density bulleted summary of key facts, updated "
        "relationship dynamics, or milestones learned. Write the summary from the companion's "
        "first-person perspective (e.g., 'The user taught me...', 'We discussed...'). "
        "When timestamps are present, keep rough timing (e.g. 'In mid-July…', 'a few days later…') "
        "so later recall has a sense of when things happened. "
        "Be incredibly concise. Do not include introductory text or markdown wrappers."
    )

    messages = [
        {"role": "system", "content": compaction_system_instruction},
        {
            "role": "user",
            "content": f"CHAT LOGS TO COMPACT:\n{raw_transcript_block}",
        },
    ]

    try:
        logger.info(
            "Processing %s stale Companion log entries for persona %s via %s...",
            len(stale_rows),
            persona_id,
            CHAT_COMPLETIONS_URL,
        )
        compiled_memory_text = chat_completion(messages, temperature=0.2, timeout=180.0)
        if not compiled_memory_text:
            raise ValueError("Empty compaction response from llama-server")
    except Exception as e:
        logger.error(
            "LLM compilation request timed out or failed: %s. "
            "Aborting compaction to save logs. "
            "(Needs llama-server on %s — run via ChatRouter startup, not before it.)",
            e,
            CHAT_COMPLETIONS_URL,
        )
        return False

    try:
        with surface_scope(SURFACE_COMPANION):
            memory_id = add_memory(
                compiled_memory_text,
                importance_score=5,
                metadata={
                    "source": "history_compactor",
                    "persona_id": persona_id,
                    "surface": SURFACE_COMPANION,
                    "max_stale_id": max_stale_id,
                },
                collection=COLLECTION_LIFE,
            )
        if not memory_id:
            raise RuntimeError("relationship_life write was refused")
        logger.info("Archived compacted memory into ChromaDB as %s", memory_id)
    except Exception as e:
        logger.error(
            "Failed to store semantic memory in ChromaDB: %s. Aborting delete.",
            e,
        )
        return False

    with sqlite3.connect(_db(surface), timeout=30.0) as write_conn:
        write_conn.execute("PRAGMA journal_mode=WAL;")
        write_cursor = write_conn.cursor()
        try:
            write_cursor.execute(
                """
                DELETE FROM chat_logs
                WHERE persona_id=? AND surface=? AND id <= ?
                """,
                (persona_id, SURFACE_COMPANION, max_stale_id),
            )
            logger.info(
                "Successfully archived persona %s Companion entries up to log ID %s.",
                persona_id,
                max_stale_id,
            )
        except sqlite3.Error as database_exception:
            logger.error(
                "Database error during chat_log purge: %s. Rollback executed.",
                database_exception,
            )
            return False

    return True


def compact_and_summarize_history(keep_last_n=50, surfaces=None):
    """
    Trim each client store's short-term history, per persona.

    Companion rows are summarized into Companion's relationship_life. Assistant rows
    are purged without any summary, so IDE coding dumps can never re-enter Companion
    memory via compaction.
    """
    targets = tuple(surfaces or SURFACES)
    compacted_any = False
    for surface in targets:
        ensure_mind_db(surface)
        with sqlite3.connect(_db(surface), timeout=30.0) as conn:
            persona_ids = [
                str(row[0])
                for row in conn.execute(
                    "SELECT DISTINCT persona_id FROM chat_logs ORDER BY persona_id"
                ).fetchall()
            ]
        for persona_id in persona_ids:
            try:
                if surface == SURFACE_COMPANION:
                    done = _compact_persona_history(persona_id, keep_last_n)
                else:
                    done = _purge_stale_rows(persona_id, SURFACE_ASSISTANT, keep_last_n)
                compacted_any = done or compacted_any
            except Exception:
                logger.exception(
                    "History compaction failed for %s persona %s", surface, persona_id
                )
        if compacted_any:
            with sqlite3.connect(_db(surface), timeout=60.0) as rebuild_conn:
                rebuild_conn.execute("VACUUM;")

    if not compacted_any:
        logger.info(
            "Database balance optimal. Every persona surface is at or below %s rows.",
            keep_last_n,
        )
    return compacted_any


if __name__ == "__main__":
    compact_and_summarize_history()
