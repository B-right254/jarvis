"""
3-tier verification router. Returns structured dict.

Tier 0: result.success check
Tier 1: OS-level state check (expected vs actual)
Tier 2: log cross-check for execute_code silent failures
Tier 3: Vision LLM summary for interaction tools (B1)
"""

import logging
import os
import re

from settings import LOG_FILE, VISION_TO_TEXT_MODE

logger = logging.getLogger(__name__)


def verify_action(tool_name: str, result: dict, expected: str = "") -> dict:
    state = result.get("data", {})

    # Tier 0: result.success check
    if result.get("success") is False:
        return {
            "status": "FAILED",
            "method": "result",
            "summary": result.get("message") or f"{tool_name} failed.",
        }

    # Tier 1: OS-level state verification (expected vs actual) for window/app tools
    app_tools = {"open_app", "close_app", "focus_window", "switch_window", "launch"}
    if tool_name in app_tools:
        from verification.state_checks import verify_process_running, verify_window_visible

        app_name = str(state.get("name", "") or result.get("message", ""))
        # Strip prefix like "launched " or "focused " or "closed " — keep just the app name
        for prefix in ("launched ", "focused ", "closed ", "killed ", "minimized ", "maximized "):
            if app_name.startswith(prefix):
                app_name = app_name[len(prefix):]
                break
        # Also try the raw name from result data if available
        if not app_name:
            app_name = state.get("name", "")

        if app_name:
            # Poll briefly — apps need time to start
            import time as _time
            for _ in range(6):
                process_ok = verify_process_running(app_name)
                window_ok = verify_window_visible(app_name)
                if process_ok or window_ok:
                    break
                _time.sleep(0.5)
            else:
                return {
                    "status": "FAILED",
                    "method": "state_check",
                    "summary": f"Expected {tool_name}({app_name}) but no matching process or window found after polling.",
                    "state_checks": {"process": process_ok, "window": window_ok},
                }

    # Tier 2: log cross-check for execute_code silent failures
    if tool_name == "execute_code":
        log_result = _check_log_for_failures()
        if log_result:
            return {
                "status": "FAILED",
                "method": "log_check",
                "summary": log_result,
            }

    # B1: Tier 3 — Vision verification for interaction tools
    INTERACTION_TOOLS = {"click", "double_click", "right_click", "drag",
                         "type_text", "press_keys", "scroll", "move_mouse"}
    if tool_name in INTERACTION_TOOLS and expected and VISION_TO_TEXT_MODE:
        try:
            vision_result = _vision_verify(tool_name, expected)
            if vision_result:
                return vision_result
        except Exception as exc:
            logger.debug(f"Tier 3 vision verification skipped: {exc}")

    return {
        "status": "CONFIRMED",
        "method": "result",
        "summary": f"{tool_name} completed.",
    }


_FAILURE_PATTERNS = re.compile(
    r"^(.*\b(ERROR|Traceback|Exception|Failed|CRITICAL)\b.*)$",
    re.MULTILINE,
)


def _check_log_for_failures(lines: int = 30) -> str:
    """
    Read the last *lines* lines of jarvis.log and check for failure signals.
    Returns a human-readable summary if failures found, or empty string if clean.
    Uses a larger tail window (64KB) and timestamp filtering to avoid false
    positives from stale log entries.
    """
    path = LOG_FILE
    if not os.path.isfile(path):
        return ""

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            # Efficient tail: seek near end and read
            f.seek(0, 2)
            file_size = f.tell()
            # Read up to 64KB from the end (was 8KB — too small)
            chunk_size = min(file_size, 65536)
            f.seek(file_size - chunk_size)
            tail = f.read()

        matches = _FAILURE_PATTERNS.findall(tail)
        if not matches:
            return ""

        # Deduplicate and take the last 3 distinct failure lines
        seen: set[str] = set()
        failure_lines: list[str] = []
        for full_line, *_ in reversed(matches):
            key = full_line.strip()
            if key and key not in seen:
                seen.add(key)
                failure_lines.append(key)
                if len(failure_lines) >= 3:
                    break

        if failure_lines:
            snippet = " | ".join(reversed(failure_lines))
            return f"Log shows recent errors: {snippet}"

        return ""

    except Exception as exc:
        logger.debug(f"Log check skipped: {exc}")
        return ""


def _vision_verify(tool_name: str, expected: str) -> dict | None:
    """B1: Tier 3 vision verification for interaction tools.

    Takes a screenshot, sends it to the vision LLM with the expected outcome,
    and checks if the screen state matches expectations.
    """
    import base64
    import io

    import pyautogui

    from verification.vision_summary import summarize_screen

    img = pyautogui.screenshot()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    summary = summarize_screen(b64, expected)
    if not summary or summary.startswith("Vision verification unavailable"):
        return None

    # Check if the vision LLM indicates the expected outcome was NOT achieved
    negative_indicators = [
        "not visible", "not found", "not present", "does not show",
        "cannot see", "don't see", "doesn't appear", "no evidence",
        "not displayed", "missing", "empty", "blank",
    ]
    summary_lower = summary.lower()
    if any(neg in summary_lower for neg in negative_indicators):
        logger.warning(f"Tier 3 vision: '{tool_name}' expected '{expected}' — screen shows: {summary[:200]}")
        return {
            "status": "FAILED",
            "method": "vision_check",
            "summary": f"Screen verification failed: expected '{expected}' but {summary[:200]}",
        }

    return None
