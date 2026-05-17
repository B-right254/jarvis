"""
Unified memory interface. Routes reads/writes to episodic or semantic layers.
"""

import logging
import time

from memory import episodic, semantic

logger = logging.getLogger(__name__)


class MemoryManager:
    def __init__(self, session_id: str = None):
        self.session_id = session_id or f"session_{int(time.time())}"
        episodic.init_db()
        semantic.init_db()
        logger.info(f"MemoryManager initialized (session={self.session_id})")

    def write_episodic(
        self,
        event_type: str,
        command_text: str = None,
        tool_name: str = None,
        tool_params: dict = None,
        tool_result: dict = None,
        success: bool = None,
        user_feedback: str = None,
    ):
        episodic.write(
            self.session_id,
            event_type,
            command_text,
            tool_name,
            tool_params,
            tool_result,
            success,
            user_feedback,
        )

    def get_recent_episodes(self, limit: int = 20) -> list[dict]:
        return episodic.get_session_events(self.session_id, limit)

    def get_cross_session_context(self, limit: int = 10) -> str:
        """Returns a formatted string of recent successful commands across all sessions
        for injection into the LLM system prompt."""
        commands = episodic.get_successful_commands(limit)
        texts = [e["command_text"] for e in commands if e.get("command_text")]
        if not texts:
            return ""
        return "Past successful commands: " + "; ".join(texts)

    def observe_pattern(self, key: str, value):
        """Feed an observed value to the pattern learner for potential preference inference.
        Call this after each successful command."""
        semantic.infer_if_consistent(key, value)

    def prune_old_episodes(self, days: int = 90):
        """Delete episodic records older than N days and cap the table at 10000 rows."""
        episodic.prune_old(days)

    def set_preference(
        self, key: str, value, confidence: float = 1.0, source: str = "explicit"
    ):
        semantic.upsert(key, value, confidence, source)

    def get_preference(self, key: str, default=None):
        return semantic.fetch(key, default)

    def get_context_summary(self) -> str:
        """Returns a short text summary of relevant preferences and frequent commands
        for prompt injection."""
        lines = []
        prefs = semantic.get_all()
        if prefs:
            pref_lines = [f"{k}: {v}" for k, v in list(prefs.items())[:5]]
            lines.append("User preferences: " + "; ".join(pref_lines))
        freq = episodic.get_command_frequency(limit=5)
        if freq:
            cmd_texts = [entry["command_text"] for entry in freq]
            lines.append("Frequently used commands: " + "; ".join(cmd_texts))
        return "\n".join(lines)
