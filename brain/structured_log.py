"""
Structured JSON logging for the ReAct tool loop.
Writes JSON-Lines to a dedicated file for monitoring and debugging.
"""

import json
import logging
import time
from pathlib import Path

from settings import LOGS_DIR

_logger = logging.getLogger(__name__)

_LOG_PATH = LOGS_DIR / "tool_loop.ndjson"


def _ensure_log_dir():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _write(entry: dict):
    _ensure_log_dir()
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as exc:
        _logger.debug(f"structured_log write failed: {exc}")


def tool_call(
    iteration: int,
    tool_name: str,
    args: dict,
    success: bool,
    duration_ms: float,
    error: str | None = None,
    cached: bool = False,
):
    _write({
        "event": "tool_call",
        "ts": time.time(),
        "iteration": iteration,
        "tool": tool_name,
        "args": args,
        "success": success,
        "duration_ms": round(duration_ms, 1),
        "cached": cached,
        "error": error,
    })


def tool_retry(
    iteration: int,
    tool_name: str,
    attempt: int,
    error: str,
):
    _write({
        "event": "tool_retry",
        "ts": time.time(),
        "iteration": iteration,
        "tool": tool_name,
        "attempt": attempt,
        "error": error,
    })


def loop_iteration(
    iteration: int,
    llm_latency_ms: float,
    tool_count: int,
    success: bool,
):
    _write({
        "event": "loop_iteration",
        "ts": time.time(),
        "iteration": iteration,
        "llm_latency_ms": round(llm_latency_ms, 1),
        "tool_count": tool_count,
        "success": success,
    })


def loop_complete(
    total_iterations: int,
    total_tools: int,
    success: bool,
    error: str | None = None,
):
    _write({
        "event": "loop_complete",
        "ts": time.time(),
        "total_iterations": total_iterations,
        "total_tools": total_tools,
        "success": success,
        "error": error,
    })


def guard_triggered(
    tool_name: str,
    iteration: int,
    reason: str,
):
    _write({
        "event": "guard_triggered",
        "ts": time.time(),
        "tool": tool_name,
        "iteration": iteration,
        "reason": reason,
    })


def state_transition(
    from_state: str,
    to_state: str,
    trigger: str,
):
    _write({
        "event": "state_transition",
        "ts": time.time(),
        "from": from_state,
        "to": to_state,
        "trigger": trigger,
    })
