"""
Memory tool — gives the LLM active control over Jarvis's long-term memory.

Actions
-------
store   — save a key/value preference or fact explicitly
          (e.g. key="user_docs_path", value="D:/Work/Docs")
recall  — retrieve a stored value by key; returns None if not found
forget  — delete a stored key permanently
summary — return a compact text digest of all preferences + frequent commands
search  — full-text search across episodic history (recent commands)

Design note: this wraps memory.episodic + memory.semantic directly so the
tool works even before a MemoryManager session has been initialised.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)


def memory(
    action: str,
    key: str = None,
    value=None,
    query: str = None,
    limit: int = 10,
) -> dict:
    """
    Interact with Jarvis long-term memory.

    Returns a standard {success, ...} dict in all cases.
    """
    try:
        # ── Lazy imports so the tool can be imported at test time without a DB ─
        from memory import episodic, semantic

        episodic.init_db()
        semantic.init_db()

        # ── store ─────────────────────────────────────────────────────────────
        if action == "store":
            if key is None or value is None:
                return {
                    "success": False,
                    "error": "action 'store' requires 'key' and 'value'",
                }
            semantic.upsert(key, value, confidence=1.0, source="explicit")
            logger.info(f"memory.store: '{key}' = {value!r}")
            return {"success": True, "action": "store", "key": key, "value": value}

        # ── recall ────────────────────────────────────────────────────────────
        elif action == "recall":
            if key is None:
                return {
                    "success": False,
                    "error": "action 'recall' requires 'key'",
                }
            value = semantic.fetch(key, default=None)
            found = value is not None
            logger.info(f"memory.recall: '{key}' → {'found' if found else 'not found'}")
            return {
                "success": True,
                "action": "recall",
                "key": key,
                "value": value,
                "found": found,
            }

        # ── forget ────────────────────────────────────────────────────────────
        elif action == "forget":
            if key is None:
                return {
                    "success": False,
                    "error": "action 'forget' requires 'key'",
                }
            from settings import MEMORY_DB
            from core.thread_db import get_connection

            conn = get_connection(MEMORY_DB, timeout=5.0)
            c = conn.cursor()
            c.execute("DELETE FROM preferences WHERE key = ?", (key,))
            deleted = c.rowcount > 0
            conn.commit()

            logger.info(f"memory.forget: '{key}' — deleted={deleted}")
            return {
                "success": True,
                "action": "forget",
                "key": key,
                "deleted": deleted,
            }

        # ── summary ───────────────────────────────────────────────────────────
        elif action == "summary":
            prefs = semantic.get_all()
            freq = episodic.get_command_frequency(limit=limit)
            recent = episodic.get_successful_commands(limit=limit)

            summary_lines = []
            if prefs:
                summary_lines.append("Stored preferences:")
                for k, v in prefs.items():
                    summary_lines.append(f"  {k}: {v}")
            if freq:
                summary_lines.append("Most frequent commands:")
                for e in freq:
                    summary_lines.append(f"  {e['command_text']}")
            if recent and not freq:
                summary_lines.append("Recent successful commands:")
                for e in recent:
                    summary_lines.append(f"  {e['command_text']}")

            text = "\n".join(summary_lines) if summary_lines else "Memory is empty."
            return {
                "success": True,
                "action": "summary",
                "summary": text,
                "preference_count": len(prefs),
            }

        # ── search ────────────────────────────────────────────────────────────
        elif action == "search":
            if not query:
                return {
                    "success": False,
                    "error": "action 'search' requires 'query'",
                }
            from settings import MEMORY_DB
            from core.thread_db import get_connection

            conn = get_connection(MEMORY_DB, timeout=5.0)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            rows = c.execute(
                """
                SELECT command_text, tool_name, success, timestamp
                FROM episodes
                WHERE command_text LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (f"%{query}%", limit),
            ).fetchall()
            results = [dict(r) for r in rows]

            logger.info(f"memory.search: '{query}' → {len(results)} results")
            return {
                "success": True,
                "action": "search",
                "query": query,
                "results": results,
                "count": len(results),
            }

        else:
            return {
                "success": False,
                "error": f"Unknown action '{action}'. Valid: store, recall, forget, summary, search",
            }

    except Exception as e:
        logger.error(f"memory({action}): {e}", exc_info=True)
        return {"success": False, "error": str(e)}
