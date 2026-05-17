"""
Multi-signal confidence gate.
Combines per-tool confidence with LLM uncertainty detection and action risk.
"""

import logging

from settings import CONFIDENCE_THRESHOLD

logger = logging.getLogger(__name__)

# Phrases that strongly indicate LLM uncertainty — significantly reduce confidence
_HIGH_UNCERTAINTY_PHRASES = [
    "i'm not sure",
    "i am not sure",
    "i don't know",
    "i do not know",
    "not confident",
    "not certain",
    "might cause issues",
    "could break",
    "irreversible",
    "cannot guarantee",
    "unsure whether",
    "risky operation",
    "potentially dangerous",
    "this could go wrong",
]

# Phrases that mildly suggest uncertainty — slightly reduce confidence
_MILD_UNCERTAINTY_PHRASES = [
    "might",
    "probably",
    "possibly",
    "i think",
    "perhaps",
    "maybe",
    "should work",
    "likely",
    "i believe",
    "seems like",
    "approximately",
    "i assume",
    "roughly",
    "i expect",
]

# Risk classification delegated to risk_classifier.classify_risk()
# (duplicate lists removed — single source of truth in risk_classifier)


def check(plan: dict) -> tuple[bool, str]:
    """
    Multi-signal confidence gate.

    Args:
        plan: dict with keys:
            - confidence: float (required) — base confidence from orchestrator
            - llm_response: str (optional) — LLM content text to scan for uncertainty
            - tool_name: str (optional) — for per-tool risk escalation
            - destructive: bool (optional) — explicit destructive flag

    Returns:
        (ok: bool, reason: str) — reason is empty string when ok=True
    """
    base_confidence = plan.get("confidence", 1.0)
    llm_response = plan.get("llm_response", "")
    tool_name = plan.get("tool_name", "")
    destructive = plan.get("destructive", False)

    # A3: Server-side risk classification — never trust LLM self-reported risk
    from safety.risk_classifier import classify_risk
    server_risk = classify_risk(tool_name, plan)
    if server_risk == "high":
        destructive = True

    confidence = float(base_confidence)

    # ── Signal 1: LLM response uncertainty analysis ────────────────────────
    if llm_response:
        text = llm_response.lower()
        # Count all uncertainty signals — multiple signals compound
        high_count = sum(1 for p in _HIGH_UNCERTAINTY_PHRASES if p in text)
        mild_count = sum(1 for p in _MILD_UNCERTAINTY_PHRASES if p in text)
        if high_count > 0:
            confidence *= 0.70 ** high_count
            logger.debug(
                f"confidence_gate: {high_count} high-uncertainty phrase(s) → {confidence:.2f}"
            )
        elif mild_count > 0:
            confidence *= 0.88 ** mild_count
            logger.debug(
                f"confidence_gate: {mild_count} mild-uncertainty phrase(s) → {confidence:.2f}"
            )

    # ── Signal 2: Explicit destructive flag ───────────────────────────────
    if destructive:
        confidence = min(confidence, 0.75)
        logger.debug(f"confidence_gate: destructive=True → capped at {confidence:.2f}")

    # ── Threshold selection — use server-side risk classification ────────────
    threshold = float(CONFIDENCE_THRESHOLD)
    if server_risk == "high":
        threshold = max(threshold, 0.80)
    elif server_risk == "medium":
        threshold = max(threshold, 0.72)

    if confidence >= threshold:
        return True, ""

    reason = (
        f"Confidence {confidence:.2f} (base {base_confidence:.2f}) "
        f"below threshold {threshold:.2f} for tool '{tool_name or 'unknown'}'"
    )
    logger.info(f"confidence_gate: BLOCKED — {reason}")
    return False, reason
