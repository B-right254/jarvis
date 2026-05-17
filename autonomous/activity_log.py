"""
Summarizes autonomous task runs for user review.
Generates human-readable reports from action logs.

Simplified: formatting is plain text without emoji decoration.
The LLM is better suited to generate rich summaries from raw task data.
"""

import logging
import time
from datetime import datetime

from autonomous.task_queue import get_all_tasks, get_pending_tasks, get_task

logger = logging.getLogger(__name__)


def generate_summary(task_id: str = None, since: float = None) -> str:
    if since is None:
        since = time.time() - 86400

    if task_id:
        task = get_task(task_id)
        if not task:
            return f"Task '{task_id}' not found."
        return _format_single_task(task)

    tasks = get_all_tasks(since=since)
    if not tasks:
        return "No autonomous activity in the last 24 hours."

    completed = [t for t in tasks if t["status"] == "complete"]
    failed = [t for t in tasks if t["status"] == "failed"]
    pending = [t for t in tasks if t["status"] == "pending"]
    running = [t for t in tasks if t["status"] == "running"]

    since_str = datetime.fromtimestamp(since).strftime("%Y-%m-%d %H:%M")
    lines = [
        f"Autonomous Activity ({since_str} — now)",
        f"  {len(completed)} completed  {len(failed)} failed  {len(pending)} pending  {len(running)} running",
        "",
    ]

    for task in sorted(tasks, key=lambda t: t.get("created_at", 0), reverse=True)[:10]:
        lines.append(_format_single_task(task))
        lines.append("")

    return "\n".join(lines)


def _format_single_task(task: dict) -> str:
    created = (
        datetime.fromtimestamp(task.get("created_at", 0)).strftime("%H:%M")
        if task.get("created_at")
        else "N/A"
    )
    started = (
        datetime.fromtimestamp(task["started_at"]).strftime("%H:%M")
        if task.get("started_at")
        else "N/A"
    )

    lines = [
        f"[{task['status']}] {task['command'][:70]}{'...' if len(task['command']) > 70 else ''}",
        f"  Created: {created} | Started: {started}",
    ]

    if task.get("error"):
        lines.append(f"  Error: {task['error'][:100]}")
    if task.get("result") and isinstance(task["result"], dict):
        response = task["result"].get("response", "")
        if response:
            lines.append(f"  Response: {response[:100]}{'...' if len(response) > 100 else ''}")

    return "\n".join(lines)


def get_pending_approvals() -> list[dict]:
    pending = []
    for task in get_pending_tasks():
        if task["status"] == "pending" and task.get("confidence_required", 0) > 0.8:
            pending.append({
                "task_id": task["task_id"],
                "command": task["command"],
                "confidence_required": task["confidence_required"],
                "created_at": task["created_at"],
            })
    return pending
