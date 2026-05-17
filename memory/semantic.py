"""
Semantic memory: stable facts about user and environment.
Preferences, frequently used apps, working patterns.
SQLite key-value store with confidence scoring.
Optimized with connection pooling for reduced latency.
"""

import json
import logging
import time

from core.thread_db import connection_context
from settings import MEMORY_DB

logger = logging.getLogger(__name__)


def init_db():
    """Initialize semantic memory schema using pooled connection."""
    schema = """
        CREATE TABLE IF NOT EXISTS preferences (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,          -- JSON value
            confidence REAL DEFAULT 1.0,  -- 1.0 = explicit, 0.5-0.9 = inferred
            source TEXT DEFAULT 'explicit', -- 'explicit' | 'inferred' | 'corrected'
            updated_at REAL NOT NULL
        )
    """
    
    with connection_context(MEMORY_DB) as conn:
        c = conn.cursor()
        c.execute(schema)
        conn.commit()
    
    logger.info("Semantic memory DB initialized")


def upsert(key: str, value, confidence: float = 1.0, source: str = "explicit"):
    """Insert or replace a preference (was named 'set', which shadowed the builtin)."""
    with connection_context(MEMORY_DB) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT OR REPLACE INTO preferences (key, value, confidence, source, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """,
            (key, json.dumps(value), confidence, source, time.time()),
        )
        conn.commit()
    
    logger.info(f"semantic.upsert('{key}') = {value} (conf={confidence}, src={source})")


def fetch(key: str, default=None):
    """Return a preference value by key (was named 'get', which shadowed the builtin)."""
    with connection_context(MEMORY_DB) as conn:
        c = conn.cursor()
        row = c.execute(
            "SELECT value FROM preferences WHERE key = ?", (key,)
        ).fetchone()
    
    if row:
        return json.loads(row[0])
    return default


def get_all() -> dict:
    with connection_context(MEMORY_DB) as conn:
        c = conn.cursor()
        rows = c.execute("SELECT key, value FROM preferences").fetchall()
    
    return {k: json.loads(v) for k, v in rows}


def get_relevant_insights(suggested_tools: list[str], max_insights: int = 3) -> list[str]:
    """
    Retrieve insights that correlate with the suggested tools.
    Filters out insights recommending tools not in the suggested list.

    Args:
        suggested_tools: Tools selected by the main LLM for this query
        max_insights: Maximum number of insights to return

    Returns:
        List of insight text strings relevant to the current tools
    """
    all_prefs = get_all()

    # Collect all insights (prefixed with "insight:")
    all_insights: list[str] = []
    for key, value in all_prefs.items():
        if not key.startswith("insight:") or not isinstance(value, str) or len(value) <= 10:
            continue
        all_insights.append(value)

    # No suggested tools → return general insights (those not mentioning specific tools)
    if not suggested_tools:
        general = [
            v for v in all_insights
            if not any(t in v.lower() for t in [
                "read_pc_state", "execute_code", "vision_query",
                "capture_screen", "control_window", "control_input", "find_on_screen",
                "file_ops", "web_search", "notify_user", "time_calendar",
                "ask_user", "schedule", "memory", "speak",
                "browser",
            ])
        ]
        return general[-max_insights:] if general else all_insights[-max_insights:]

    suggested_set = set(suggested_tools)

    relevant = []
    for value in all_insights:
        insight_lower = value.lower()

        # Check if insight mentions any tool name from suggested set
        tools_in_insight = set()
        for tool in suggested_set:
            if tool.replace("_", " ") in insight_lower or tool in insight_lower:
                tools_in_insight.add(tool)

        # Keep insight if it mentions tools in our suggested set
        # OR if it doesn't mention any specific tool (general advice)
        mentions_tools = any(
            t in insight_lower
            for t in ["read_pc_state", "execute_code", "vision_query",
                     "capture_screen", "control_window", "control_input", "find_on_screen",
                     "file_ops", "web_search", "notify_user", "time_calendar",
                     "ask_user", "schedule", "memory", "speak",
                     "browser"]
        )

        if not mentions_tools or tools_in_insight:
            relevant.append(value)

    return relevant[-max_insights:]


def infer_if_consistent(key: str, observed_value, min_occurrences: int = 5):
    """If same value observed repeatedly, auto-set as inferred preference."""
    value_json = json.dumps(observed_value)
    now = time.time()
    
    with connection_context(MEMORY_DB) as conn:
        c = conn.cursor()
        # Ensure the tally table exists (created lazily alongside the main schema)
        c.execute("""
            CREATE TABLE IF NOT EXISTS inference_tallies (
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                PRIMARY KEY (key, value_json)
            )
        """)
        # INSERT OR IGNORE so the first_seen is preserved on subsequent calls
        c.execute(
            """
            INSERT OR IGNORE INTO inference_tallies
                (key, value_json, count, first_seen, last_seen)
            VALUES (?, ?, 0, ?, ?)
            """,
            (key, value_json, now, now),
        )
        c.execute(
            """
            UPDATE inference_tallies
            SET count = count + 1, last_seen = ?
            WHERE key = ? AND value_json = ?
            """,
            (now, key, value_json),
        )
        row = c.execute(
            "SELECT count FROM inference_tallies WHERE key = ? AND value_json = ?",
            (key, value_json),
        ).fetchone()
        count = row[0] if row else 0
        conn.commit()
    
    if count >= min_occurrences:
        upsert(key, observed_value, confidence=0.7, source="inferred")
        logger.info(
            f"semantic.infer_if_consistent: auto-inferred '{key}' = {observed_value} "
            f"(observed {count} times)"
        )
