"""
Episodic memory: session history. What happened, when, result.
SQLite backend. Append-only. Queryable by session_id or time range.
Optimized with connection pooling for reduced latency.
"""

import json
import logging
import re
import sqlite3
import time

from settings import MEMORY_DB
from core.thread_db import connection_context

logger = logging.getLogger(__name__)


def init_db():
    """Initialize episodic memory schema using pooled connection."""
    MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)
    schema = """
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            event_type TEXT NOT NULL,      -- 'command', 'tool_call', 'tool_result', 'error'
            command_text TEXT,
            tool_name TEXT,
            tool_params TEXT,              -- JSON
            tool_result TEXT,              -- JSON summary
            success INTEGER,               -- 1 or 0
            user_feedback TEXT             -- 'correction', 'approval', null
        )
    """
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_episodes_time ON episodes(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_episodes_command_text ON episodes(command_text)",
    ]
    
    with connection_context(MEMORY_DB) as conn:
        c = conn.cursor()
        c.execute(schema)
        for idx in indexes:
            c.execute(idx)
        conn.commit()
    
    logger.info("Episodic memory DB initialized")


def write(
    session_id: str,
    event_type: str,
    command_text: str = None,
    tool_name: str = None,
    tool_params: dict = None,
    tool_result: dict = None,
    success: bool = None,
    user_feedback: str = None,
):
    """Write an episode to memory using pooled connection."""
    with connection_context(MEMORY_DB) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO episodes (session_id, timestamp, event_type, command_text,
                                  tool_name, tool_params, tool_result, success, user_feedback)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                session_id,
                time.time(),
                event_type,
                command_text,
                tool_name,
                json.dumps(tool_params) if tool_params else None,
                json.dumps(tool_result) if tool_result else None,
                1 if success else 0 if success is not None else None,
                user_feedback,
            ),
        )
        conn.commit()


def get_session_events(session_id: str, limit: int = 50) -> list[dict]:
    """Get session events using pooled connection."""
    with connection_context(MEMORY_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        rows = c.execute(
            """
            SELECT * FROM episodes WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?
        """,
            (session_id, limit),
        ).fetchall()
    
    events = []
    for r in rows:
        event = dict(r)
        if event.get("tool_params"):
            event["tool_params"] = json.loads(event["tool_params"])
        if event.get("tool_result"):
            event["tool_result"] = json.loads(event["tool_result"])
        events.append(event)
    return list(reversed(events))  # Chronological order


def get_recent(limit: int = 20) -> list[dict]:
    """Get recent events using pooled connection."""
    with connection_context(MEMORY_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        rows = c.execute(
            "SELECT * FROM episodes ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    
    return [dict(r) for r in reversed(rows)]


def get_successful_commands(limit: int = 20) -> list[dict]:
    """Cross-session query: recent successful command events across all sessions."""
    with connection_context(MEMORY_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        rows = c.execute(
            """
            SELECT * FROM episodes
            WHERE event_type = 'command' AND success = 1 AND command_text IS NOT NULL
            ORDER BY timestamp DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    
    events = []
    for r in rows:
        event = dict(r)
        if event.get("tool_params"):
            event["tool_params"] = json.loads(event["tool_params"])
        if event.get("tool_result"):
            event["tool_result"] = json.loads(event["tool_result"])
        events.append(event)
    return list(reversed(events))  # Chronological order


def prune_old(days: int = 90):
    """Delete episodes older than N days; also trim the table to at most 10000 rows."""
    cutoff = time.time() - days * 86400
    with connection_context(MEMORY_DB) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM episodes WHERE timestamp < ?", (cutoff,))
        deleted_time = c.rowcount
        # Keep at most 10000 rows by removing the oldest beyond that cap
        c.execute(
            """
            DELETE FROM episodes WHERE id NOT IN (
                SELECT id FROM episodes ORDER BY timestamp DESC LIMIT 10000
            )
            """
        )
        deleted_cap = c.rowcount
        conn.commit()
    
    logger.info(
        f"episodic.prune_old(days={days}): removed {deleted_time} time-expired rows, "
        f"{deleted_cap} rows over 10000-row cap"
    )


def get_command_frequency(limit: int = 20) -> list[dict]:
    """Return the most frequently issued commands across all sessions."""
    with connection_context(MEMORY_DB) as conn:
        c = conn.cursor()
        rows = c.execute(
            """
            SELECT command_text, COUNT(*) AS count
            FROM episodes
            WHERE event_type = 'command' AND command_text IS NOT NULL
            GROUP BY command_text
            ORDER BY count DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [{"command_text": row[0], "count": row[1]} for row in rows]


def search_by_similarity(query: str, limit: int = 3) -> list[dict]:
    """B5: Find past episodes with command text similar to the query.

    Uses keyword-based SQL matching since ChromaDB isn't wired for episodic.
    Returns the most relevant past outcomes (command + result + success).
    """
    # Extract meaningful keywords (3+ chars, skip common words)
    skip = {"the", "and", "for", "you", "are", "but", "not", "with", "this",
            "that", "from", "have", "was", "can", "all", "how", "what", "when",
            "open", "close", "get", "set", "my", "is", "it", "to", "in", "on",
            "at", "of", "or", "me", "do", "if", "by", "up", "out", "no", "yes"}
    keywords = [w.lower() for w in re.findall(r'\b\w{3,}\b', query) if w.lower() not in skip]
    if not keywords:
        return []

    # Build SQL: score by number of keyword matches, return most relevant
    with connection_context(MEMORY_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        # Find episodes where command_text contains at least one keyword
        like_clauses = " OR ".join(f"LOWER(command_text) LIKE ?" for _ in keywords)
        params = [f"%{kw}%" for kw in keywords]
        rows = c.execute(
            f"""
            SELECT command_text, tool_result, success, timestamp
            FROM episodes
            WHERE event_type = 'command' AND command_text IS NOT NULL
            AND ({like_clauses})
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            params + [limit * 3],  # fetch more, then score
        ).fetchall()

    # Score by number of matching keywords
    scored = []
    for r in rows:
        cmd = (r["command_text"] or "").lower()
        score = sum(1 for kw in keywords if kw in cmd)
        if score > 0:
            entry = dict(r)
            if entry.get("tool_result"):
                entry["tool_result"] = json.loads(entry["tool_result"])
            entry["match_score"] = score
            scored.append(entry)

    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored[:limit]
