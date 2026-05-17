import logging
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

import settings
from core.thread_db import get_connection

logger = logging.getLogger(__name__)


def _connect():
    return get_connection(settings.SKILLS_DB, timeout=5.0)


def init_db():
    if not settings.ENABLE_SKILLS:
        return
    settings.SKILLS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            skill_id TEXT PRIMARY KEY,
            intent_label TEXT NOT NULL,
            code TEXT NOT NULL,
            language TEXT DEFAULT 'python',
            status TEXT DEFAULT 'candidate',
            run_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            success_rate REAL DEFAULT 0.0,
            last_used TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            embedding_generated BOOLEAN DEFAULT 0
        )
    """)
    conn.commit()
    logger.info("Skill store DB initialized")


def save_candidate(intent_label: str, code: str, language: str = "python") -> str:
    if not settings.ENABLE_SKILLS:
        return ""
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT skill_id FROM skills WHERE intent_label = ? AND code = ?",
            (intent_label, code),
        ).fetchone()
        if existing:
            return existing[0]
        skill_id = f"skill_{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO skills (skill_id, intent_label, code, language, status) VALUES (?, ?, ?, ?, 'candidate')",
            (skill_id, intent_label, code, language),
        )
        conn.commit()
        logger.info(f"Saved candidate skill {skill_id} for {intent_label}")
    except Exception as e:
        logger.error(f"Failed to save candidate: {e}")
        return ""

    return skill_id


def promote_skill(skill_id: str, conn=None):
    if not settings.ENABLE_SKILLS:
        return
    if conn is None:
        conn = _connect()
    try:
        row = conn.execute(
            "SELECT intent_label, code FROM skills WHERE skill_id = ?", (skill_id,)
        ).fetchone()
        if not row:
            logger.warning(f"Skill {skill_id} not found for promotion")
            return
        intent_label, code = row
        conn.execute(
            "UPDATE skills SET status = 'active' WHERE skill_id = ?",
            (skill_id,),
        )
        conn.commit()
        logger.info(f"Promoted skill {skill_id} to active")
    except Exception as e:
        logger.error(f"Failed to promote skill {skill_id}: {e}")


def record_run(skill_id: str, success: bool):
    """Update run stats. Lifecycle promotion/demotion/retirement is handled by the LLM via prompt instructions."""
    if not settings.ENABLE_SKILLS:
        return
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT run_count, success_count, failure_count FROM skills WHERE skill_id = ?",
            (skill_id,),
        ).fetchone()
        if not row:
            return
        run_count, success_count, failure_count = row
        run_count += 1
        if success:
            success_count += 1
        else:
            failure_count += 1
        success_rate = success_count / run_count if run_count > 0 else 0.0
        conn.execute(
            "UPDATE skills SET run_count=?, success_count=?, failure_count=?, success_rate=?, last_used=? WHERE skill_id=?",
            (run_count, success_count, failure_count, success_rate, datetime.now().isoformat(), skill_id),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to record run for {skill_id}: {e}")


def get_skill(skill_id: str) -> Optional[dict]:
    if not settings.ENABLE_SKILLS:
        return None
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM skills WHERE skill_id = ?", (skill_id,)).fetchone()
        if not row:
            return None
        columns = [col[1] for col in conn.execute("PRAGMA table_info(skills)").fetchall()]
        return dict(zip(columns, row))
    except Exception as e:
        logger.error(f"Failed to get skill {skill_id}: {e}")
        return None


def get_candidate_by_intent(intent: str) -> Optional[dict]:
    if not settings.ENABLE_SKILLS:
        return None
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM skills WHERE status = 'candidate' AND lower(intent_label) = lower(?) ORDER BY run_count DESC LIMIT 1",
            (intent,),
        ).fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"get_candidate_by_intent error: {e}")
        return None


def search_by_intent(intent: str) -> Optional[dict]:
    """Return the best active skill matching intent. Uses SQL keyword + exact match."""
    if not settings.ENABLE_SKILLS:
        return None

    conn = _connect()
    conn.row_factory = sqlite3.Row

    # Extract meaningful keywords (3+ chars, skip common words)
    import re
    skip = {"the", "and", "for", "you", "are", "but", "not", "with", "this",
            "that", "from", "have", "was", "can", "all", "how", "what", "when",
            "open", "close", "get", "set", "my", "is", "it", "to", "in", "on",
            "at", "of", "or", "me", "do", "if", "by", "up", "out", "no", "yes"}
    intent_lower = intent.lower()
    keywords = [w for w in re.findall(r'\b\w{3,}\b', intent_lower) if w not in skip]

    if keywords:
        # Fetch active skills and score by keyword match count
        rows = conn.execute(
            "SELECT * FROM skills WHERE status = 'active'"
        ).fetchall()
        scored = []
        for row in rows:
            label = (row["intent_label"] or "").lower()
            score = sum(1 for kw in keywords if kw in label)
            if score > 0:
                entry = dict(row)
                entry["match_score"] = score
                scored.append(entry)
        if scored:
            scored.sort(key=lambda x: (x["match_score"], x.get("success_rate", 0)), reverse=True)
            return scored[0]

    # Fall back to exact match
    row = conn.execute(
        "SELECT * FROM skills WHERE status = 'active' AND lower(intent_label) = lower(?) ORDER BY success_rate DESC LIMIT 1",
        (intent,),
    ).fetchone()
    return dict(row) if row else None


def get_active_skills(limit: int = 100) -> list[dict]:
    if not settings.ENABLE_SKILLS:
        return []
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM skills WHERE status = 'active' LIMIT ?", (limit,)).fetchall()
        columns = [col[1] for col in conn.execute("PRAGMA table_info(skills)").fetchall()]
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        logger.error(f"Failed to get active skills: {e}")
        return []


def delete_skill(skill_id: str) -> bool:
    if not settings.ENABLE_SKILLS:
        return False
    conn = _connect()
    try:
        conn.execute("DELETE FROM skills WHERE skill_id = ?", (skill_id,))
        conn.commit()
        logger.info(f"Deleted skill {skill_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete skill {skill_id}: {e}")
        return False


def prune_candidates():
    if not settings.ENABLE_SKILLS:
        return
    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM skills WHERE status = 'candidate'").fetchone()[0]
        if count <= settings.SKILL_CANDIDATE_CAP:
            return
        conn.execute(
            "DELETE FROM skills WHERE skill_id IN ("
            "SELECT skill_id FROM skills WHERE status = 'candidate' ORDER BY created_at ASC LIMIT ?"
            ")", (count - settings.SKILL_CANDIDATE_CAP,))
        conn.commit()
        logger.info(f"Pruned {count - settings.SKILL_CANDIDATE_CAP} candidates")
    except Exception as e:
        logger.error(f"Failed to prune candidates: {e}")
