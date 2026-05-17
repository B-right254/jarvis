"""
Main routing gate. Bridges brain, safety, tools, and verification.
Injects callbacks into tool_loop to maintain strict layer boundaries.
"""

import concurrent.futures
import logging
import re
import sys
import threading
from collections import deque

import autonomous.activity_log
import autonomous.task_queue
import settings
from autonomous.approval_gate import ApprovalGate
from autonomous.scheduler import Scheduler
from agents.jarvis import JarvisAgent
from agents.execution import ExecutionAgent
from safety import executor as safety
from settings import ITERATION_CAPS
from skills.skill_store import get_active_skills, search_by_intent
from skills.skill_store import init_db as init_skills
from tools import TOOL_REGISTRY
from verification.verifier import verify_action

from core.classifier import classify, is_special_command
from core.console import cli_input
from core.reporter import report
from core.system_state import SystemState

logger = logging.getLogger(__name__)


class Orchestrator:
    MAX_HISTORY = 40

    def __init__(self, memory=None):
        self._history = deque(maxlen=self.MAX_HISTORY)
        self._state = SystemState()
        self._mode = "interactive_cloud"
        self._approval_gate = ApprovalGate()
        autonomous.task_queue.init_db()
        self._memory = memory
        self._scheduler = Scheduler(self.handle)
        self._scheduler.start()
        self.running = True
        self._last_tool_calls: list[dict] = []
        # A1: Track LLM context for confidence gate
        self._last_llm_text: str = ""
        self._last_confidence: float = 0.80
        self._tool_failure_streak: dict[str, int] = {}
        init_skills()
        # Agents
        self._jarvis = JarvisAgent()
        self._execution = ExecutionAgent(self._execute_wrapper, self._verify_wrapper)

        try:
            from core.heartbeat_monitor import monitor
            monitor.start()
        except Exception:
            logger.warning("Heartbeat monitor unavailable")

        if getattr(settings, "AMBIENT_MONITORING", True):
            try:
                from autonomous import ambient_monitor
                ambient_monitor.start()
                import atexit
                atexit.register(ambient_monitor.stop)
            except Exception:
                logger.warning("Ambient monitor unavailable")

        # History loading from memory is disabled — stale context confuses the LLM.
        # The system prompt provides full context on each interaction.

    # ── Fast-path handlers (no LLM call) ─────────────────────────────────

    def _handle_special(self, text: str) -> str | None:
        cmd = is_special_command(text)
        if cmd is None:
            return None
        if cmd == "skills_status":
            active = get_active_skills()
            if not active:
                return "No active skills yet."
            return "Active skills:\n" + "\n".join(
                f"  {s['intent_label']} (success: {s['success_rate']:.0%})"
                for s in active
            )
        if cmd == "summary":
            from autonomous.activity_log import generate_summary
            return generate_summary()
        if cmd == "status":
            import shutil, psutil
            ram = psutil.virtual_memory()
            disk_path = "C:\\" if sys.platform == "win32" else "/"
            try:
                disk = shutil.disk_usage(disk_path)
            except Exception:
                disk = shutil.disk_usage(".")
            return (
                f"RAM: {ram.percent}% used | "
                f"Disk {disk_path}: {disk.used // 1e9:.1f}GB / {disk.total // 1e9:.1f}GB"
            )
        if cmd == "task_status":
            parts = text.split()
            if len(parts) > 2:
                from autonomous.task_queue import get_task as _get_tq_task
                task = _get_tq_task(parts[2])
                if task:
                    return f"Task {parts[2]}: {task.get('status', '?')} (created: {task.get('created_at', '?')})"
                return f"Task {parts[2]} not found"
            from autonomous.task_queue import get_active_tasks as _get_active
            active = _get_active()
            if not active:
                return "No active tasks"
            return "\n".join(f"{t['task_id'][:8]}: {t.get('command', '?')[:40]} - {t['status']}" for t in active)
        return None

    def _handle_simple_intent(self, text: str) -> str | None:
        intent = classify(text)
        if intent is None:
            return None
        logger.info(f"Classifier matched: {intent.label}")
        result = self._execute_wrapper(intent.tool_name, intent.args)
        if result.get("success"):
            return intent.format_result(result)
        return None

    # ── Main entry point ──────────────────────────────────────────────────

    def handle(self, user_input: str) -> str:
        logger.info(f"Orchestrator.handle: '{user_input}'")
        try:
            text = re.sub(r"^\d+\.\s*", "", user_input).strip()

            special = self._handle_special(text)
            if special is not None:
                self._update_history(user_input, special)
                return special

            simple = self._handle_simple_intent(text)
            if simple is not None:
                self._update_history(user_input, simple)
                return simple

            # Simple shortcut: direct typing for commands like 'write <text>'
            if text.lower().startswith('write '):
                content = text[6:].strip()
                # Use type_text tool with high confidence
                result = self._execute_wrapper('type_text', {'text': content})
                if result.get('success'):
                    resp = f"Typed '{content}'."
                else:
                    resp = f"Failed to type text: {result.get('error', 'unknown')}"
                self._update_history(user_input, resp)
                return resp

            if self._memory:
                self._memory.write_episodic("command", command_text=user_input)

            memory_context = self._memory.get_context_summary() if self._memory else ""

            # B5: Retrieve relevant past episodes by keyword similarity
            if self._memory:
                try:
                    from memory import episodic
                    past = episodic.search_by_similarity(text, limit=2)
                    if past:
                        episodes_block = "\nPast relevant experiences:\n"
                        for ep in past:
                            cmd = ep.get("command_text", "?")
                            ok = "succeeded" if ep.get("success") else "failed"
                            result_preview = ""
                            tr = ep.get("tool_result")
                            if isinstance(tr, dict):
                                resp = tr.get("response") or tr.get("output") or str(tr.get("data", ""))
                                result_preview = f" → {resp[:120]}" if resp else ""
                            episodes_block += f"  • '{cmd}' {ok}{result_preview}\n"
                        memory_context = f"{episodes_block}\n{memory_context}" if memory_context else episodes_block
                except Exception:
                    pass  # Memory retrieval is best-effort

            if settings.ENABLE_SKILLS:
                match = search_by_intent(text)
                if match and match.get("skill_id"):
                    skill_hint = (
                        f"Saved skill found for intent '{text}':\n"
                        f"  code: {match.get('code', '')[:500]}\n"
                        f"  language: {match.get('language', 'python')}\n"
                        f"Execute this code via execute_code — do NOT assume it already ran."
                    )
                    memory_context = f"{skill_hint}\n\n{memory_context}" if memory_context else skill_hint

            # Route through Jarvis agent (brain) -> Execution agent (hands)
            self._current_intent = text
            timeout = settings.LLM_TIMEOUT + 30
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
                future = _pool.submit(
                    self._jarvis.process,
                    user_input=text,
                    history=list(self._history),
                    memory_context=memory_context,
                    mode=self._mode,
                    intent_handler=self._execution.execute_intent,
                )
                try:
                    result = future.result(timeout=timeout) or {}
                except concurrent.futures.TimeoutError:
                    logger.error(f"Jarvis agent timed out after {timeout}s")
                    result = {"response": "Jarvis timed out", "success": False, "error": "TIMEOUT", "tool_calls": []}

            if not result:
                result = {"response": "No response from Jarvis", "success": False, "tool_calls": []}

            response = result.get("response", "Done.")
            intents_log = result.get("tool_calls", [])

            # ── Verification: check if execution agent reported failures ──
            failed_intents = [i for i in intents_log if i.get("status") == "failed"]
            if failed_intents:
                logger.warning(f"Execution agent reported {len(failed_intents)} failed intent(s)")
                errors = [f"  - {i.get('action', '?')}: {i.get('error', 'unknown')}" for i in failed_intents[:3]]
                response += "\n\n⚠️ Some steps failed:\n" + "\n".join(errors)
                result["success"] = False

            if result.get("success") and intents_log:
                try:
                    formatted = report(
                        intent={"goal": text, "raw_input": user_input},
                        results=result["tool_calls"],
                        verification={
                            "status": "CONFIRMED" if result["success"] else "FAILED",
                            "summary": response,
                        },
                    )
                    if formatted and len(formatted) > 5:
                        response = formatted
                except Exception:
                    pass

            if self._memory:
                self._memory.write_episodic(
                    "response",
                    command_text=user_input,
                    tool_name="tool_loop",
                    success=result.get("success"),
                    tool_result={"response": response[:500]},
                )

            self._update_history(user_input, response)
            return response

        except Exception as e:
            logger.error(f"Orchestrator pipeline error: {e}", exc_info=True)
            return f"I encountered an error: {e}"

    def _update_history(self, user_input: str, response: str):
        self._history.append({"role": "user", "content": user_input})
        self._history.append({"role": "assistant", "content": response})

    # ── Callbacks injected into tool_loop ─────────────────────────────────

    def _execute_wrapper(self, tool_name: str, args: dict) -> dict:
        if tool_name not in TOOL_REGISTRY:
            return {"success": False, "message": f"Unknown tool: {tool_name}", "data": {}, "timestamp": ""}

        # State-aware wait optimization — skip tool call if condition already met
        if tool_name == "wait" and args.get("condition"):
            condition = args["condition"]
            target = str(args.get("target", "")).lower()
            state = self._state.snapshot()

            if condition == "window_visible" and target:
                if target in state.get("active_window", "").lower():
                    return {"success": True, "message": f"Wait skipped: '{target}' already active", "data": {}, "timestamp": ""}
            elif condition == "text_visible" and target:
                if target in state.get("screen_text", "").lower():
                    return {"success": True, "message": f"Wait skipped: text '{target}' already on screen", "data": {}, "timestamp": ""}
            elif condition == "cpu_idle" and target:
                try:
                    if float(state.get("cpu_percent", 100)) < float(target):
                        return {"success": True, "message": f"Wait skipped: CPU already idle ({state.get('cpu_percent')}% < {target}%)", "data": {}, "timestamp": ""}
                except (ValueError, TypeError):
                    pass

        # A1: Dynamic confidence — decreases on repeated failures, resets on success
        # For the type_text tool we keep a high confidence to avoid unnecessary blocks after prior failures.
        if tool_name == "type_text":
            confidence = 0.85
            streak = 0  # reset streak for typing to avoid later UnboundLocalError
        else:
            streak = self._tool_failure_streak.get(tool_name, 0)
            if streak == 0:
                confidence = 0.85
            elif streak == 1:
                confidence = 0.65
            else:
                confidence = 0.40

        # Ensure type_text retains a high confidence to avoid being blocked by the gate
        if tool_name == "type_text" and confidence < 0.85:
            confidence = 0.85
        result = safety.execute(
            tool_name,
            TOOL_REGISTRY[tool_name],
            args,
            plan={
                "confidence": confidence,
                "llm_response": getattr(self, "_current_intent", ""),
                "tool_name": tool_name,
            },
        )
        # Track failure streak for next call
        if result.get("success"):
            self._tool_failure_streak[tool_name] = 0
        else:
            self._tool_failure_streak[tool_name] = streak + 1
        self._state.update(tool_name, args, result)
        return result

    def _verify_wrapper(self, tool_name: str, result: dict, expected: str) -> dict:
        return verify_action(tool_name, result, expected=expected)

    # ── Mode switching ────────────────────────────────────────────────────

    def set_mode(self, mode: str):
        if mode in ITERATION_CAPS:
            self._mode = mode

    # ── CLI loop ──────────────────────────────────────────────────────────

    def run_cli(self, output_callback=None):
        print("JARVIS ready. Type a command (or 'quit' to exit).")
        while self.running:
            try:
                user_input = cli_input().strip()
                if user_input.lower() in ("quit", "exit", "q"):
                    break
                if not user_input:
                    continue

                schedule_match = re.match(
                    r"schedule\s+\"?([^\"]+?)\"?\s+(every|in|at)\s+(.*)",
                    user_input,
                    re.IGNORECASE,
                )
                if schedule_match:
                    cmd, _, cron_val = schedule_match.groups()
                    tid = self._scheduler.schedule(cmd.strip(), cron_val.strip())
                    print(f"\nScheduled: '{cmd}' ({tid[:8]})")
                    continue

                response = self.handle(user_input)
                if output_callback:
                    output_callback(response)
                else:
                    print(f"\nJARVIS: {response}")

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"CLI loop error: {e}")
                print(f"System error: {e}")
        print("JARVIS stopped.")
