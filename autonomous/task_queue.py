"""
Task queue for autonomous operation.
States: pending → approved → running → complete | failed | paused
"""

import json
import logging
import sqlite3
import time
import uuid

from settings import MEMORY_DB
from core.thread_db import get_connection

logger = logging.getLogger(__name__)

TASK_STATES = ["pending", "approved", "running", "complete", "failed", "paused"]


def _connect():
    """Get a thread-local connection to MEMORY_DB."""
    return get_connection(MEMORY_DB, timeout=5.0)


def init_db():
    MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS autonomous_tasks (
            task_id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            confidence_required REAL DEFAULT 0.85,
            created_at REAL NOT NULL,
            scheduled_for REAL DEFAULT 0,
            started_at REAL,
            completed_at REAL,
            result TEXT,
            action_log TEXT,
            error TEXT
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON autonomous_tasks(status)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_scheduled ON autonomous_tasks(scheduled_for)"
    )
    conn.commit()
    logger.info("Autonomous task queue DB initialized")


def create_task(
    command: str, confidence_required: float = 0.85, scheduled_for: float = 0
) -> str:
    task_id = str(uuid.uuid4())
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO autonomous_tasks
        (task_id, command, confidence_required, created_at, scheduled_for, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    """,
        (task_id, command, confidence_required, time.time(), scheduled_for),
    )
    conn.commit()
    label = repr(command) if len(command) <= 50 else repr(command[:50]) + "..."
    logger.info(f"task_queue: created task '{task_id[:8]}' — {label}")
    return task_id


def claim_task(task_id: str) -> bool:
    """
    Atomically claim a pending task by transitioning it to 'running'.
    Returns True if the task was successfully claimed, False if another
    scheduler already claimed it (TOCTOU-safe).
    """
    conn = _connect()
    c = conn.cursor()
    c.execute(
        "UPDATE autonomous_tasks SET status = 'running', started_at = ? WHERE task_id = ? AND status = 'pending'",
        (time.time(), task_id),
    )
    conn.commit()
    claimed = c.rowcount > 0
    if claimed:
        logger.info(f"task_queue: claimed task '{task_id[:8]}' (pending → running)")
    return claimed


def get_pending_tasks() -> list[dict]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    now = time.time()
    rows = c.execute(
        """
        SELECT * FROM autonomous_tasks
        WHERE status = 'pending' AND (scheduled_for = 0 OR scheduled_for <= ?)
        ORDER BY created_at ASC
    """,
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_task(
    task_id: str,
    status: str,
    result: dict = None,
    error: str = None,
    action_log: list = None,
):
    if status not in TASK_STATES:
        raise ValueError(f"Invalid status: {status}")
    conn = _connect()
    c = conn.cursor()
    updates = ["status = ?"]
    params = [status]
    if status == "running":
        updates.append("started_at = ?")
        params.append(time.time())
    elif status in ("complete", "failed", "paused"):
        updates.append("completed_at = ?")
        params.append(time.time())
    if result is not None:
        updates.append("result = ?")
        params.append(json.dumps(result))
    if error is not None:
        updates.append("error = ?")
        params.append(error)
    if action_log is not None:
        updates.append("action_log = ?")
        params.append(json.dumps(action_log))
    params.append(task_id)
    c.execute(
        f"UPDATE autonomous_tasks SET {', '.join(updates)} WHERE task_id = ?",
        params,
    )
    conn.commit()
    logger.info(f"task_queue: task '{task_id[:8]}' → {status}")


def get_task(task_id: str) -> dict | None:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    row = c.execute(
        "SELECT * FROM autonomous_tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    if row:
        task = dict(row)
        if task.get("result"):
            task["result"] = json.loads(task["result"])
        if task.get("action_log"):
            task["action_log"] = json.loads(task["action_log"])
        return task
    return None


def get_all_tasks(since: float = None) -> list[dict]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if since:
        rows = c.execute(
            "SELECT * FROM autonomous_tasks WHERE created_at >= ? ORDER BY created_at ASC",
            (since,),
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT * FROM autonomous_tasks ORDER BY created_at ASC"
        ).fetchall()
    tasks = []
    for row in rows:
        task = dict(row)
        if task.get("result"):
            task["result"] = json.loads(task["result"])
        if task.get("action_log"):
            task["action_log"] = json.loads(task["action_log"])
        tasks.append(task)
    return tasks


def get_active_tasks() -> list[dict]:
    """Return all tasks currently in 'running' status."""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    rows = c.execute(
        "SELECT * FROM autonomous_tasks WHERE status = 'running' ORDER BY created_at ASC"
    ).fetchall()
    tasks = []
    for row in rows:
        task = dict(row)
        if task.get("result"):
            task["result"] = json.loads(task["result"])
        if task.get("action_log"):
            task["action_log"] = json.loads(task["action_log"])
        tasks.append(task)
    return tasks


def get_tasks_by_status(status: str) -> list[dict]:
    """Return all tasks with the given status."""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    rows = c.execute(
        "SELECT * FROM autonomous_tasks WHERE status = ? ORDER BY created_at ASC",
        (status,),
    ).fetchall()
    tasks = []
    for row in rows:
        task = dict(row)
        if task.get("result"):
            task["result"] = json.loads(task["result"])
        if task.get("action_log"):
            task["action_log"] = json.loads(task["action_log"])
        tasks.append(task)
    return tasks


def delete_completed_tasks(older_than_days: int = 7):
    """Clean up old completed/failed tasks to prevent DB bloat."""
    conn = _connect()
    c = conn.cursor()
    cutoff = time.time() - (older_than_days * 86400)
    c.execute(
        """
        DELETE FROM autonomous_tasks
        WHERE status IN ('complete', 'failed') AND completed_at < ?
    """,
        (cutoff,),
    )
    deleted = c.rowcount
    conn.commit()
    if deleted:
        logger.info(f"task_queue: deleted {deleted} old tasks")
