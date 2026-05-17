
"""Lightweight tool call validator (BATCH_TOOL_PLAN parsing removed)."""
import json
import logging

logger = logging.getLogger(__name__)


def validate_tool_calls(tool_calls: list[dict], valid_tools: set) -> tuple:
    if not tool_calls:
        return True, ""
    for tc in tool_calls:
        name = tc.get("function", {}).get("name", "")
        args = tc.get("function", {}).get("arguments", {})
        if name not in valid_tools:
            return False, f"Unknown tool requested: {name}"
        if not isinstance(args, dict):
            return False, f"Tool '{name}' arguments must be a JSON object"
    return True, ""
