"""
Skill Runner — executes stored skills through the safety funnel and records outcome.

Simplified: post-execution app-launch verification removed. The LLM self-verifies
by calling read_pc_state() after skill execution. The skill store's record_run()
tracks raw execution success/failure for lifecycle management.
"""

from __future__ import annotations

import logging
from typing import Dict

from safety.executor import execute
import settings
from tools import TOOL_REGISTRY

from skills.skill_store import get_skill, record_run

logger = logging.getLogger(__name__)


def run_skill(skill_id: str, intent: str) -> Dict:
    if not settings.ENABLE_SKILLS:
        return {"success": False, "error": "Skills disabled", "skill_id": skill_id, "intent": intent}

    skill = get_skill(skill_id)
    if not skill:
        return {"success": False, "error": "Skill not found", "skill_id": skill_id, "intent": intent}
    if skill["status"] == "retired":
        return {"success": False, "error": "Skill retired", "skill_id": skill_id, "intent": intent}

    try:
        tool_name = "execute_code"
        tool_fn = TOOL_REGISTRY[tool_name]
        args = {"code": skill["code"], "language": skill["language"]}

        result = execute(
            tool_name=tool_name,
            tool_fn=tool_fn,
            args=args,
            plan={"confidence": 0.95, "source": f"skill:{skill_id}"},
        )

        success = result.get("success", False)
        record_run(skill_id, success)

        return {
            "success": success,
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "error": result.get("error", ""),
            "skill_id": skill_id,
            "intent": intent,
        }

    except Exception as exc:
        logger.error(f"skill_runner: skill '{skill_id[:8]}' raised unexpectedly: {exc}", exc_info=True)
        record_run(skill_id, False)
        return {"success": False, "error": str(exc), "skill_id": skill_id, "intent": intent}
