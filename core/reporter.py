"""
Result reporter — formats tool execution results into human-readable responses.
Called by the orchestrator after the tool loop completes.

Per-tool formatting is removed. The LLM sees tool results directly in its
context and can format responses naturally. This module handles coarse
success/failure/uncertain routing only.
"""

import logging

logger = logging.getLogger(__name__)


def report(intent: dict, results: list[dict], verification: dict) -> str:
    if not results:
        return ""

    v_status = verification.get("status", "INCONCLUSIVE")
    v_summary = verification.get("summary", "")

    last_result = results[-1]
    last_err = last_result.get("result", {}).get("error", "")

    if v_status == "CONFIRMED":
        return v_summary or "Done."
    elif v_status == "FAILED":
        return last_err[:200] or v_summary[:200] or "Task failed."
    else:
        return v_summary or last_err or ""
