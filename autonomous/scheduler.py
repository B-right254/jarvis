"""
Cron-style scheduler for autonomous tasks.

Simplified: regex-based cron parser, risk-keyword matching, and recurring
pattern detection removed. The LLM interprets schedule expressions and sets
appropriate confidence. This module handles only the timed execution loop
and DB persistence for recurring schedules.
"""

import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta

import settings
from settings import MEMORY_DB
from core.thread_db import get_connection

from autonomous.approval_gate import ApprovalGate
from autonomous.task_queue import create_task, get_pending_tasks, update_task, claim_task as _claim_task_atomic

logger = logging.getLogger(__name__)

_APPROVAL_TIMEOUT = int(getattr(settings, "APPROVAL_TIMEOUT_SECONDS", 60))


def _init_recurring_db():
    conn = get_connection(MEMORY_DB, timeout=5.0)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recurring_schedules (
            task_id         TEXT PRIMARY KEY,
            command         TEXT,
            cron_expression TEXT,
            next_run        REAL,
            created_at      REAL,
            active          INTEGER DEFAULT 1
        )
    """)
    conn.commit()


class Scheduler:
    def __init__(self, orchestrator_callback):
        self._orchestrator = orchestrator_callback
        self._stop_event = threading.Event()
        self._thread = None
        self._scheduled: dict[str, dict] = {}
        self._gate = ApprovalGate(timeout_seconds=_APPROVAL_TIMEOUT)
        _init_recurring_db()
        self._load_recurring_from_db()

    def schedule(self, command: str, cron_expression: str, task_id: str | None = None) -> str:
        from uuid import uuid4
        task_id = task_id or str(uuid4())
        scheduled_for = self._parse_cron(cron_expression)
        if scheduled_for is None:
            raise ValueError(f"Unrecognized schedule: '{cron_expression}'")

        self._scheduled[task_id] = {"command": command, "cron": cron_expression, "next_run": scheduled_for}
        create_task(command, scheduled_for=scheduled_for)

        if cron_expression.lower().startswith("every"):
            self._persist_recurring(task_id, command, cron_expression, scheduled_for)

        label = repr(command) if len(command) <= 40 else repr(command[:40]) + "..."
        logger.info(f"scheduler: scheduled task '{task_id[:8]}' — {label} @ {datetime.fromtimestamp(scheduled_for)}")
        return task_id

    def cancel(self, task_id: str) -> dict:
        removed = task_id in self._scheduled
        if removed:
            del self._scheduled[task_id]
        db_updated = False
        try:
            conn = get_connection(MEMORY_DB, timeout=5.0)
            conn.execute("UPDATE recurring_schedules SET active = 0 WHERE task_id = ?", (task_id,))
            db_updated = conn.execute("SELECT changes()").fetchone()[0] > 0
            conn.commit()
        except Exception as exc:
            logger.warning(f"scheduler: could not deactivate '{task_id[:8]}' in DB: {exc}")
        if removed or db_updated:
            logger.info(f"scheduler: cancelled recurring task '{task_id[:8]}'")
            return {"success": True, "task_id": task_id}
        logger.warning(f"scheduler: cancel: task '{task_id[:8]}' not found")
        return {"success": False, "reason": "task_not_found", "task_id": task_id}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _monitor_loop(self):
        logger.info("scheduler: monitor loop started")
        while not self._stop_event.is_set():
            try:
                # Use atomic status transition to avoid TOCTOU races
                pending = get_pending_tasks()
                for task in pending:
                    task_id = task["task_id"]
                    # Atomically claim this task — only one scheduler instance wins
                    claimed = _claim_task_atomic(task_id)
                    if claimed:
                        self._handle_task(task)
            except Exception as e:
                logger.error(f"scheduler: monitor error: {e}")

            now = time.time()
            for task_id, entry in list(self._scheduled.items()):
                if entry["next_run"] > now:
                    continue
                command = entry["command"]
                cron = entry["cron"]
                logger.info(f"scheduler: recurring '{task_id[:8]}' due — '{command[:40]}'")
                try:
                    self._orchestrator(command)
                except Exception as exc:
                    logger.error(f"scheduler: recurring '{task_id[:8]}' failed: {exc}")

                if cron.lower().startswith("every"):
                    next_run = self._parse_cron(cron)
                    if next_run:
                        self._scheduled[task_id]["next_run"] = next_run
                        self._update_next_run_db(task_id, next_run)
                else:
                    del self._scheduled[task_id]

            self._stop_event.wait(30)
        logger.info("scheduler: monitor loop stopped")

    def _handle_task(self, task: dict) -> None:
        task_id = task["task_id"]
        command = task["command"]
        confidence = float(task.get("confidence_required", 0.85))

        approved = self._gate.request(task_id, command, confidence)
        if not approved:
            logger.warning(f"scheduler: task '{task_id[:8]}' was NOT approved — skipping")
            update_task(task_id, "failed", error="Denied by approval gate")
            return

        logger.info(f"scheduler: executing task '{task_id[:8]}' — '{command[:40]}...'")
        update_task(task_id, "running")
        try:
            result = self._orchestrator(command)
            action_log = []
            try:
                orch = getattr(self._orchestrator, "__self__", None)
                if orch and hasattr(orch, "_last_tool_calls"):
                    action_log = [
                        {"tool": e.get("tool"), "args": e.get("args"), "success": e.get("result", {}).get("success", False)}
                        for e in orch._last_tool_calls
                    ]
            except Exception:
                pass
            update_task(task_id, "complete", result={"response": result}, action_log=action_log)
        except Exception as e:
            logger.error(f"scheduler: task '{task_id[:8]}' failed: {e}")
            update_task(task_id, "failed", error=str(e))

    def _persist_recurring(self, task_id: str, command: str, cron_expression: str, next_run: float):
        try:
            conn = get_connection(MEMORY_DB, timeout=5.0)
            conn.execute(
                "INSERT OR REPLACE INTO recurring_schedules (task_id, command, cron_expression, next_run, created_at, active) VALUES (?, ?, ?, ?, ?, 1)",
                (task_id, command, cron_expression, next_run, time.time()),
            )
            conn.commit()
        except Exception as exc:
            logger.warning(f"scheduler: could not persist recurring schedule '{task_id[:8]}': {exc}")

    def _update_next_run_db(self, task_id: str, next_run: float):
        try:
            conn = get_connection(MEMORY_DB, timeout=5.0)
            conn.execute("UPDATE recurring_schedules SET next_run = ? WHERE task_id = ?", (next_run, task_id))
            conn.commit()
        except Exception as exc:
            logger.warning(f"scheduler: could not update next_run for '{task_id[:8]}': {exc}")

    def _load_recurring_from_db(self):
        try:
            conn = get_connection(MEMORY_DB, timeout=5.0)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT task_id, command, cron_expression, next_run FROM recurring_schedules WHERE active = 1"
            ).fetchall()
            now = time.time()
            for row in rows:
                task_id = row["task_id"]
                cron = row["cron_expression"]
                next_run = row["next_run"]
                if next_run <= now:
                    recalculated = self._parse_cron(cron)
                    if recalculated:
                        next_run = recalculated
                        self._update_next_run_db(task_id, next_run)
                self._scheduled[task_id] = {"command": row["command"], "cron": cron, "next_run": next_run}
            if rows:
                logger.info(f"scheduler: reloaded {len(rows)} recurring schedule(s) from DB")
        except Exception as exc:
            logger.warning(f"scheduler: could not load recurring schedules from DB: {exc}")

    def _parse_cron(self, expr: str) -> float | None:
        now = time.time()
        expr = expr.lower().strip()

        if expr.startswith("every "):
            rest = expr[6:].strip()
            if rest.endswith("minutes") or rest.endswith("minute"):
                try:
                    n = int(rest.split()[0])
                    return now + n * 60
                except (ValueError, IndexError):
                    pass
            if rest.endswith("hours") or rest.endswith("hour"):
                try:
                    n = int(rest.split()[0])
                    return now + n * 3600
                except (ValueError, IndexError):
                    pass
            if rest.startswith("day at "):
                try:
                    time_part = rest[7:].strip()
                    h, m = int(time_part.split(":")[0]), int(time_part.split(":")[1])
                    if not (0 <= h <= 23 and 0 <= m <= 59):
                        return None
                    target = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
                    ts = target.timestamp()
                    return ts if ts > now else ts + 86400
                except (ValueError, IndexError):
                    pass

        if expr.startswith("in "):
            rest = expr[3:].strip()
            try:
                parts = rest.split()
                n = int(parts[0])
                if n <= 0:
                    return None
                unit = parts[1] if len(parts) > 1 else "minutes"
                return now + n * (60 if unit.startswith("minute") else 3600)
            except (ValueError, IndexError):
                pass

        if "at " in expr:
            try:
                time_part = expr.split("at ")[-1].strip()
                h, m = int(time_part.split(":")[0]), int(time_part.split(":")[1])
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    return None
                # Use timezone-aware datetime for DST-safe computation
                target = datetime.now().astimezone().replace(hour=h, minute=m, second=0, microsecond=0)
                ts = target.timestamp()
                return ts if ts > now else ts + 86400
            except (ValueError, IndexError):
                pass

        return None
