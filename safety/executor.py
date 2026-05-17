"""
Unified safety funnel. All tool calls pass through here.
Wraps every tool result in a standard envelope:
  {success, message, data, timestamp}
"""

import datetime
import json
import logging
from pathlib import Path

from safety import audit_log
from safety.confidence_gate import check as confidence_check
from safety.plan_validator import validate as plan_validate
from safety.tool_guard import check_paths

logger = logging.getLogger(__name__)


_SCHEMAS_PATH = Path(__file__).parent.parent / "tools" / "schemas.json"
_SCHEMAS_CACHE = None


def _get_tool_schema(tool_name: str) -> dict | None:
    """Return the input schema for *tool_name* from schemas.json, or None."""
    global _SCHEMAS_CACHE
    try:
        if _SCHEMAS_CACHE is None:
            with open(_SCHEMAS_PATH, encoding="utf-8") as f:
                _SCHEMAS_CACHE = json.load(f)
        entry = _SCHEMAS_CACHE.get(tool_name, {})
        return entry.get("input", {})
    except Exception:
        return None


def _validate_args(tool_name: str, args: dict) -> str | None:
    """Validate args against the tool's schema. Returns error string or None."""
    schema = _get_tool_schema(tool_name)
    if not schema:
        return None  # no schema = no validation
    props = schema.get("properties", {})
    required = schema.get("required", [])

    # Check required params
    for key in required:
        if key not in args or args[key] in (None, ""):
            return f"Missing required parameter '{key}' for {tool_name}"

    # Check types for known params (only str, int, bool, list, object)
    for key, value in args.items():
        if key not in props:
            continue
        prop = props[key]
        ptype = prop.get("type", "")
        if ptype == "integer" and not isinstance(value, int):
            return f"Parameter '{key}' should be integer, got {type(value).__name__}"
        if ptype == "boolean" and not isinstance(value, bool):
            return f"Parameter '{key}' should be boolean, got {type(value).__name__}"
        if ptype == "string" and not isinstance(value, str):
            return f"Parameter '{key}' should be string, got {type(value).__name__}"
        if ptype == "array" and not isinstance(value, list):
            return f"Parameter '{key}' should be array, got {type(value).__name__}"
        # Check enum constraints
        enum_vals = prop.get("enum")
        if enum_vals and value not in enum_vals:
            return f"Parameter '{key}' should be one of {enum_vals}, got {value!r}"

    return None


def execute(tool_name: str, tool_fn, args: dict, plan: dict = None):
    # ── Schema validation ─────────────────────────────────────────────────
    schema_error = _validate_args(tool_name, args)
    if schema_error:
        audit_log.log_blocked(tool_name, args, schema_error)
        return {"success": False, "blocked": True, "error": schema_error}

    allowed, reason = check_paths(args)
    if not allowed:
        audit_log.log_blocked(tool_name, args, reason)
        return {"success": False, "blocked": True, "error": reason}

    language = args.get("language", "python")
    if tool_name == "execute_code":
        from safety.tool_guard import check_imports

        allowed, reason = check_imports(args.get("code", ""), language)
        if not allowed:
            audit_log.log_blocked(tool_name, args, reason)
            return {"success": False, "blocked": True, "error": reason}
        if language not in ("python", "powershell"):
            audit_log.log_blocked(tool_name, args, f"Unsupported language: {language}")
            return {
                "success": False,
                "blocked": True,
                "error": f"Unsupported language: {language}",
            }

    logger.info(
        f"Executing {tool_name} (lang={language}) with confidence={plan.get('confidence') if plan else None}"
    )

    if plan:
        proceed, reason = confidence_check(plan)
        if not proceed:
            logger.warning(f"Action paused: {reason}")
            audit_log.log_blocked(tool_name, args, reason)
            return {"success": False, "blocked": True, "error": reason, "paused": True}

        # A3: Server-side risk classification — block high-risk tools that
        # haven't been through the approval gate.
        from safety.risk_classifier import classify_risk
        if classify_risk(tool_name, args) == "high" and not plan.get("approved"):
            audit_log.log_blocked(tool_name, args, "High-risk tool requires user approval")
            return {"success": False, "blocked": True, "error": "High-risk tool requires user approval", "paused": True}

    validate_plan = {**(plan or {}), **args}
    valid, reason = plan_validate(validate_plan)
    if not valid:
        audit_log.log_blocked(tool_name, args, reason)
        return {"success": False, "blocked": True, "error": reason}

    clean_args = {k: v for k, v in args.items() if k and k.strip()}
    raw = tool_fn(**clean_args)
    if not isinstance(raw, dict):
        raw = {"success": False, "error": f"Tool returned non-dict: {type(raw).__name__}"}

    # Standard envelope: success, message, data, timestamp
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result = {
        "success": raw.get("success", False),
        "message": raw.get("error") or raw.get("status") or raw.get("message", ""),
        "data": {k: v for k, v in raw.items() if k not in ("success", "error", "status", "message")},
        "timestamp": now,
    }
    audit_log.log_call(tool_name, clean_args, result)
    return result
