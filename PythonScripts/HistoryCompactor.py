import logging
import sqlite3

from MemoryUpdater import (
    CHAT_COMPLETIONS_URL,
    DB_PATH,
    chat_completion,
    ensure_mind_db,
)
from SemanticMemory import COLLECTION_LIFE, add_memory

logging.basicConfig(level=logging.INFO, format="[Blossom Compactor]: %(message)s")
logger = logging.getLogger(__name__)


def _stale_history_for_persona(persona_id: str, keep_last_n: int):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) as total FROM chat_logs WHERE persona_id=?",
        (persona_id,),
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
        WHERE persona_id=?
        ORDER BY id ASC
        LIMIT ?
        """,
        (persona_id, rows_to_process),
    )
    stale_rows = cursor.fetchall()
    conn.close()
    return stale_rows


def _compact_persona_history(persona_id: str, keep_last_n: int) -> bool:
    stale_rows = _stale_history_for_persona(persona_id, keep_last_n)
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
            "Processing %s stale log entries for persona %s via %s...",
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
        memory_id = add_memory(
            compiled_memory_text,
            importance_score=5,
            metadata={
                "source": "history_compactor",
                "persona_id": persona_id,
                "max_stale_id": max_stale_id,
            },
            collection=COLLECTION_LIFE,
        )
        logger.info("Archived compacted memory into ChromaDB as %s", memory_id)
    except Exception as e:
        logger.error(
            "Failed to store semantic memory in ChromaDB: %s. Aborting delete.",
            e,
        )
        return False

    with sqlite3.connect(DB_PATH, timeout=30.0) as write_conn:
        write_conn.execute("PRAGMA journal_mode=WAL;")
        write_cursor = write_conn.cursor()
        try:
            write_cursor.execute(
                "DELETE FROM chat_logs WHERE persona_id=? AND id <= ?",
                (persona_id, max_stale_id),
            )
            logger.info(
                "Successfully archived persona %s entries up to log ID %s.",
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


def compact_and_summarize_history(keep_last_n=50):
    """
    Compact old short-term history independently for each persona.

    Summaries still enter the shared relationship/life collection, while raw
    conversation context and retention limits remain persona-scoped.
    """
    ensure_mind_db()
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        persona_ids = [
            str(row[0])
            for row in conn.execute(
                "SELECT DISTINCT persona_id FROM chat_logs ORDER BY persona_id"
            ).fetchall()
        ]

    compacted_any = False
    for persona_id in persona_ids:
        try:
            compacted_any = (
                _compact_persona_history(persona_id, keep_last_n) or compacted_any
            )
        except Exception:
            logger.exception("History compaction failed for persona %s", persona_id)

    if not compacted_any:
        logger.info(
            "Database balance optimal. Every persona is at or below %s rows.",
            keep_last_n,
        )
        return False

    with sqlite3.connect(DB_PATH, timeout=60.0) as rebuild_conn:
        logger.info("Reclaiming disk array spaces via VACUUM protocol...")
        rebuild_conn.execute("VACUUM;")
        logger.info("Disk space defragmentation successful.")
    return True


if __name__ == "__main__":
    compact_and_summarize_history()
