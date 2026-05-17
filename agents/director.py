"""
Jarvis Agent — Conversation + Strategic Planning.

Handles:
  - Natural conversation and reasoning
  - Deciding when action is needed
  - Memory/context
  - High-level intent planning (outputs INTENT)

Does NOT call tools directly — that's the Execution Agent's job.
"""

import json
import logging

from brain import ollama_client
from brain.context_manager import prune_history
from brain.prompt_builder import build_system_prompt
from settings import ITERATION_CAPS, MAX_CONTEXT_TOKENS, TOOL_LOOP_HISTORY_MESSAGES

logger = logging.getLogger(__name__)


class JarvisAgent:
    """Conversation + high-level planning agent (the brain)."""

    def process(
        self,
        user_input: str,
        history: list[dict],
        memory_context: str = "",
        mode: str = "interactive_cloud",
        intent_handler=None,
    ) -> dict:
        """
        Process user input through Jarvis.

        Args:
            user_input: The user's message
            history: Conversation history
            memory_context: Memory summary
            mode: Agent mode (iteration cap)
            intent_handler: Called when Jarvis outputs INTENT.
                           Receives (intent_dict) -> returns response string.

        Returns:
            dict with response, success, iterations, tool_calls
        """
        cap = ITERATION_CAPS.get(mode, 4)
        messages = self._build_messages(user_input, history, memory_context)
        tool_log = []

        for iteration in range(1, cap + 1):
            if len(json.dumps(messages)) > (MAX_CONTEXT_TOKENS * 4):
                messages = prune_history(messages)

            llm_result = ollama_client.chat(
                messages=messages,
                tools=None,
                temperature=0.3,
                reasoning_effort="medium" if iteration <= 2 else "high",
            )

            content = (llm_result.get("content") or "").strip()

            if not content and iteration >= cap:
                return {
                    "response": "I'm not sure how to help with that.",
                    "success": True,
                    "iterations": iteration,
                    "tool_calls": tool_log,
                }

            intent = self._parse_intent(content)

            if intent and intent_handler:
                messages.append({"role": "assistant", "content": content})
                exec_result = intent_handler(intent)
                tool_log.append({
                    "action": intent.get("action", "?"),
                    "target": intent.get("target", ""),
                    "status": "failed" if "failed" in exec_result.lower() else "ok",
                    "error": exec_result if "failed" in exec_result.lower() else None,
                })
                messages.append({"role": "user", "content": exec_result})
                continue

            # Chat response — Jarvis is done
            if content:
                return {
                    "response": content,
                    "success": True,
                    "iterations": iteration,
                    "tool_calls": tool_log,
                }

        return {
            "response": "Task complete.",
            "success": True,
            "iterations": cap,
            "tool_calls": tool_log,
        }

    def _build_messages(self, user_input, history, memory_context):
        messages = [{"role": "system", "content": build_system_prompt()}]
        if memory_context:
            messages.append({"role": "system", "content": memory_context})
        messages.extend(history[-TOOL_LOOP_HISTORY_MESSAGES:])
        messages.append({"role": "user", "content": user_input})
        return messages

    def _parse_intent(self, content: str) -> dict | None:
        """Parse INTENT JSON from Jarvis's response."""
        stripped = content.strip() if content else ""
        if not stripped or not stripped.startswith("INTENT"):
            return None
        try:
            json_str = stripped[len("INTENT"):].strip()
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(json_str)
            return obj
        except (json.JSONDecodeError, ValueError):
            return None
