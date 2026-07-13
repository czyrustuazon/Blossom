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


def compact_and_summarize_history(keep_last_n=50):
    """
    Extracts rows older than keep_last_n, condenses them into a
    permanent semantic memory record in ChromaDB, and drops the raw rows.
    """
    ensure_mind_db()

    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as total FROM chat_logs")
    total_rows = cursor.fetchone()["total"]

    if total_rows <= keep_last_n:
        logger.info(
            "Database balance optimal. Total rows (%s) below threshold (%s).",
            total_rows,
            keep_last_n,
        )
        conn.close()
        return False

    rows_to_process = total_rows - keep_last_n
    cursor.execute("PRAGMA table_info(chat_logs)")
    columns = {row["name"] for row in cursor.fetchall()}
    has_created_at = "created_at" in columns
    select_cols = "id, role, content, created_at" if has_created_at else "id, role, content"
    cursor.execute(
        f"SELECT {select_cols} FROM chat_logs ORDER BY id ASC LIMIT ?",
        (rows_to_process,),
    )
    stale_rows = cursor.fetchall()

    if not stale_rows:
        conn.close()
        return False

    max_stale_id = stale_rows[-1]["id"]
    conn.close()

    transcript_segments = []
    for row in stale_rows:
        speaker = "User" if row["role"] == "user" else "Companion"
        if has_created_at:
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
            "Processing %s stale log entries via %s...",
            rows_to_process,
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
            metadata={"source": "history_compactor", "max_stale_id": max_stale_id},
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
                "DELETE FROM chat_logs WHERE id <= ?",
                (max_stale_id,),
            )
            logger.info("Successfully archived entries up to log ID %s.", max_stale_id)
        except sqlite3.Error as database_exception:
            logger.error(
                "Database error during chat_log purge: %s. Rollback executed.",
                database_exception,
            )
            return False

    with sqlite3.connect(DB_PATH, timeout=60.0) as rebuild_conn:
        logger.info("Reclaiming disk array spaces via VACUUM protocol...")
        rebuild_conn.execute("VACUUM;")
        logger.info("Disk space defragmentation successful.")

    return True


if __name__ == "__main__":
    compact_and_summarize_history()
