"""
Server-side risk classification for tool calls.
Independent of LLM output — the safety layer must not trust the entity it guards.
"""

from settings import HIGH_RISK_TOOLS as _HIGH_RISK_TOOLS
from settings import MEDIUM_RISK_TOOLS as _MEDIUM_RISK_TOOLS

# Argument patterns that escalate any tool to high-risk
_ESCALATION_PATTERNS = [
    ("path", ["system32", "syswow64", "boot", "windows"]),
    ("command", ["shutdown", "restart", "format", "diskpart"]),
    ("code", ["rm -rf", "del /q", "Remove-Item -Recurse"]),
]


def classify_risk(tool_name: str, params: dict | None = None) -> str:
    """Return 'high', 'medium', or 'low' based on tool name and arguments.

    This is the single source of truth for risk classification.
    The LLM's self-reported risk_tier is ignored for safety decisions.
    """
    if tool_name in _HIGH_RISK_TOOLS:
        return "high"
    if tool_name in _MEDIUM_RISK_TOOLS:
        return "medium"

    # Check argument-based escalation
    if params:
        for key, dangerous_values in _ESCALATION_PATTERNS:
            if key in params:
                val = str(params[key]).lower()
                if any(dv in val for dv in dangerous_values):
                    return "high"

    return "low"


def requires_approval(tool_name: str, params: dict | None = None,
                      autonomous: bool = False) -> bool:
    """Return True if this call requires user approval before execution."""
    risk = classify_risk(tool_name, params)
    if risk == "high":
        return True
    if autonomous:
        # In autonomous mode, medium-risk also needs approval
        return risk == "medium"
    return False
