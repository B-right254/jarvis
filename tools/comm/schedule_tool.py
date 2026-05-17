"""
Schedule tool — lets the LLM create, list, and cancel timed tasks.

Works by writing directly to the autonomous task queue and recurring
schedules table.  The running Scheduler thread (autonomous/scheduler.py)
picks up new rows on its next tick (≤ 5 s lag).

Supported schedule expressions (same parser as Scheduler._parse_cron):
  "in 10 minutes"          → one-shot, 10 min from now
  "in 2 hours"             → one-shot, 2 h from now
  "at 09:00"               → one-shot, next 09:00
  "every 30 minutes"       → recurring every 30 min
  "every 2 hours"          → recurring every 2 h
  "every day at 07:30"     → recurring daily at 07:30
  "on Monday at 09:00"     → recurring weekly on Monday

Actions
-------
add     — schedule a new task (required: command, when)
cancel  — cancel a recurring schedule (required: task_id)
list    — show all pending / recurring scheduled tasks
"""

import logging
import re
import sqlite3
import time
import uuid
from datetime import datetime

from core.thread_db import get_connection

logger = logging.getLogger(__name__)

# ── Days of week for "on <day> at HH:MM" expressions ────────────────────────
_DAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _parse_when(expr: str) -> float | None:
    """
    Parse a human-readable schedule expression into a Unix timestamp for the
    *next* occurrence.  Returns None if the expression is not recognised.
    """
    expr = expr.lower().strip()
    now = time.time()

    # "in N minutes/hours"
    m = re.match(r"in (\d+) (minutes?|hours?)", expr)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = n * 60 if unit.startswith("minute") else n * 3600
        return now + delta

    # "at HH:MM"
    m = re.match(r"at (\d{1,2}):(\d{2})", expr)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        dt = datetime.now().replace(hour=h, minute=mn, second=0, microsecond=0)
        ts = dt.timestamp()
        return ts if ts > now else ts + 86400  # push to tomorrow if already past

    # "every N minutes"
    m = re.match(r"every (\d+) minutes?", expr)
    if m:
        return now + int(m.group(1)) * 60

    # "every N hours"
    m = re.match(r"every (\d+) hours?", expr)
    if m:
        return now + int(m.group(1)) * 3600

    # "every day at HH:MM"
    m = re.match(r"every day at (\d{1,2}):(\d{2})", expr)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        dt = datetime.now().replace(hour=h, minute=mn, second=0, microsecond=0)
        ts = dt.timestamp()
        return ts if ts > now else ts + 86400

    # "on <weekday> at HH:MM"
    m = re.match(r"on (\w+) at (\d{1,2}):(\d{2})", expr)
    if m:
        day_name = m.group(1)
        h, mn = int(m.group(2)), int(m.group(3))
        target_dow = _DAYS.get(day_name)
        if target_dow is None:
            return None
        dt = datetime.now().replace(hour=h, minute=mn, second=0, microsecond=0)
        days_ahead = (target_dow - dt.weekday()) % 7
        if days_ahead == 0 and dt.timestamp() <= now:
            days_ahead = 7
        import datetime as _dt
        dt = dt + _dt.timedelta(days=days_ahead)
        return dt.timestamp()

    return None


def _is_recurring(expr: str) -> bool:
    expr = expr.lower().strip()
    return bool(
        re.match(r"every \d+ (minutes?|hours?)", expr)
        or re.match(r"every day at", expr)
        or re.match(r"on \w+ at", expr)
    )


def schedule(
    action: str,
    command: str = None,
    when: str = None,
    task_id: str = None,
) -> dict:
    """
    Manage scheduled tasks.

    action='add'    — schedule a new task (command + when required)
    action='cancel' — cancel a recurring task (task_id required)
    action='list'   — list all pending and active recurring tasks
    """
    try:
        from settings import MEMORY_DB
        from autonomous.task_queue import init_db as _init_task_db

        _init_task_db()

        # ── add ───────────────────────────────────────────────────────────────
        if action == "add":
            if not command:
                return {"success": False, "error": "action 'add' requires 'command'"}
            if not when:
                return {"success": False, "error": "action 'add' requires 'when' (e.g. 'in 10 minutes', 'every day at 09:00')"}

            run_at = _parse_when(when)
            if run_at is None:
                return {
                    "success": False,
                    "error": (
                        f"Could not parse schedule expression: '{when}'. "
                        "Try: 'in 10 minutes', 'at 09:00', 'every day at 08:00', "
                        "'on Monday at 09:00', 'every 30 minutes'."
                    ),
                }

            new_id = task_id or str(uuid.uuid4())
            recurring = _is_recurring(when)

            # Write via task_queue module to use its connection management
            from autonomous.task_queue import create_task as _qt_create
            _qt_create(command, confidence_required=0.85, scheduled_for=run_at)
            # For recurring tasks also write to recurring_schedules so the
            # Scheduler reloads them on restart.
            if recurring:
                conn = get_connection(MEMORY_DB, timeout=5.0)
                try:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS recurring_schedules (
                            task_id         TEXT PRIMARY KEY,
                            command         TEXT,
                            cron_expression TEXT,
                            next_run        REAL,
                            created_at      REAL,
                            active          INTEGER DEFAULT 1
                        )
                        """
                    )
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO recurring_schedules
                            (task_id, command, cron_expression, next_run, created_at, active)
                        VALUES (?, ?, ?, ?, ?, 1)
                        """,
                        (new_id, command, when, run_at, time.time()),
                    )
                    conn.commit()
                finally:
                    conn.close()

            run_at_str = datetime.fromtimestamp(run_at).strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"schedule.add: '{new_id[:8]}' — {command!r} @ {run_at_str} (recurring={recurring})")
            return {
                "success": True,
                "action": "add",
                "task_id": new_id,
                "command": command,
                "when": when,
                "run_at": run_at_str,
                "recurring": recurring,
            }

        # ── cancel ────────────────────────────────────────────────────────────
        elif action == "cancel":
            if not task_id:
                return {"success": False, "error": "action 'cancel' requires 'task_id'"}

            conn = get_connection(MEMORY_DB, timeout=5.0)
            c = conn.cursor()
            # Cancel in task queue
            c.execute(
                "UPDATE autonomous_tasks SET status = 'failed' WHERE task_id = ? AND status = 'pending'",
                (task_id,),
            )
            task_rows = c.rowcount
            # Deactivate in recurring table if present
            c.execute(
                "UPDATE recurring_schedules SET active = 0 WHERE task_id = ?",
                (task_id,),
            )
            recurring_rows = c.rowcount
            conn.commit()

            found = task_rows > 0 or recurring_rows > 0
            logger.info(f"schedule.cancel: '{task_id[:8]}' — found={found}")
            return {
                "success": found,
                "action": "cancel",
                "task_id": task_id,
                "error": None if found else "task_id not found or already completed",
            }

        # ── list ──────────────────────────────────────────────────────────────
        elif action == "list":
            conn = get_connection(MEMORY_DB, timeout=5.0)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            pending = c.execute(
                """
                SELECT task_id, command, scheduled_for, status
                FROM autonomous_tasks
                WHERE status IN ('pending', 'approved')
                ORDER BY scheduled_for ASC
                LIMIT 20
                """
            ).fetchall()

            # Recurring table may not exist yet
            try:
                recurring = c.execute(
                    """
                    SELECT task_id, command, cron_expression, next_run
                    FROM recurring_schedules
                    WHERE active = 1
                    ORDER BY next_run ASC
                    """
                ).fetchall()
            except Exception:
                recurring = []

            def _fmt(ts):
                try:
                    return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    return str(ts)

            pending_list = [
                {
                    "task_id": r["task_id"],
                    "command": r["command"],
                    "run_at": _fmt(r["scheduled_for"]),
                    "status": r["status"],
                }
                for r in pending
            ]
            recurring_list = [
                {
                    "task_id": r["task_id"],
                    "command": r["command"],
                    "schedule": r["cron_expression"],
                    "next_run": _fmt(r["next_run"]),
                }
                for r in recurring
            ]

            return {
                "success": True,
                "action": "list",
                "pending": pending_list,
                "recurring": recurring_list,
                "total_pending": len(pending_list),
                "total_recurring": len(recurring_list),
            }

        else:
            return {
                "success": False,
                "error": f"Unknown action '{action}'. Valid: add, cancel, list",
            }

    except Exception as e:
        logger.error(f"schedule({action}): {e}", exc_info=True)
        return {"success": False, "error": str(e)}
