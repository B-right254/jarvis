"""
Approval Gate: Blocking confirmation flow for high-risk autonomous tasks.

Simplified: RiskLevel enum, AUTO_APPROVE_THRESHOLD, and approve/deny word sets
removed. The LLM assesses risk using prompt instructions and sets confidence
accordingly. This module handles only the user-facing prompt-and-wait flow.
"""

import logging
import threading

from core.console import cli_input

logger = logging.getLogger(__name__)


class ApprovalGate:
    def __init__(self, timeout_seconds: int = 60):
        self.timeout = timeout_seconds

    def request(self, task_id: str, command: str, confidence: float) -> bool:
        print(f"\n  [APPROVAL] Task {task_id[:8]}: {command[:80]}")
        print(f"  Confidence: {confidence:.0%}  Timeout: {self.timeout}s")
        print(f"  Type 'yes' to approve, anything else to deny.")

        result_holder: list[bool] = []
        done_event = threading.Event()

        def _reader():
            try:
                raw = cli_input("> ").strip().lower()
                result_holder.append(raw in ("yes", "y", "approve", "ok", "sure"))
            except (EOFError, OSError):
                result_holder.append(False)
            finally:
                done_event.set()

        reader_thread = threading.Thread(target=_reader, daemon=True, name="approval-reader")
        reader_thread.start()

        timed_out = not done_event.wait(timeout=self.timeout)

        if timed_out:
            print(f"\n  No response within {self.timeout}s — task denied (fail-safe).")
            logger.warning(f"approval_gate: task '{task_id[:8]}' timed out — denied")
            return False

        approved = result_holder[0] if result_holder else False
        if approved:
            logger.info(f"approval_gate: task '{task_id[:8]}' APPROVED")
        else:
            logger.warning(f"approval_gate: task '{task_id[:8]}' DENIED")
        return approved
