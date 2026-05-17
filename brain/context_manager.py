"""
Manages LLM context window budget. Prunes old turns, summarizes early context.
Uses approximate char-to-token ratio (4:1) for speed.
"""

import json
import logging

from settings import MAX_CONTEXT_TOKENS

logger = logging.getLogger(__name__)
CHARS_PER_TOKEN = 3


def estimate_tokens(text: str) -> int:
    """Estimate token count. 3 chars/token is more accurate for mixed code+prose."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def prune_history(messages: list[dict], budget: int = MAX_CONTEXT_TOKENS) -> list[dict]:
    if not messages:
        return []
    system = [m for m in messages if m["role"] == "system"]
    history = [m for m in messages if m["role"] != "system"]

    current_tokens = sum(estimate_tokens(json.dumps(m, default=str)) for m in history)
    if current_tokens <= budget * 0.8:
        return system + history[-20:]

    early = history[:-6]
    late = history[-6:]
    summary_text = _summarize_early_turns(early)
    summary_msg = {
        "role": "assistant",
        "content": f"[Context Summary of earlier turns: {summary_text}]",
    }
    return system + [summary_msg] + late


def _summarize_early_turns(early_turns: list[dict]) -> str:
    """
    Summarise early turns using the LLM. Falls back to tool-list summary
    if the LLM is unavailable or the call fails.
    """
    # Build compact transcript (cap each message at 300 chars to save tokens)
    lines = []
    for m in early_turns:
        role = m.get("role", "")
        if role not in ("user", "assistant", "tool"):
            continue
        raw = m.get("content", "")
        if not isinstance(raw, str):
            raw = str(raw)
        snippet = raw.strip()[:300]
        if snippet:
            lines.append(f"{role}: {snippet}")

    if not lines:
        return "No earlier context."

    transcript = "\n".join(lines[:12])  # at most 12 lines into the LLM

    try:
        from brain import ollama_client

        result = ollama_client.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarise the following conversation turns in 2-3 sentences. "
                        "Focus on what the user asked for and what was accomplished. "
                        "Be concise — this summary replaces the full history in context."
                    ),
                },
                {"role": "user", "content": transcript},
            ],
            tools=[],
            temperature=0.2,
        )
        summary = (result.get("content") or "").strip()
        if summary:
            logger.debug(f"context_manager: LLM summary: {summary[:120]}")
            return summary
    except Exception as exc:
        logger.warning(
            f"context_manager: LLM summarization failed — {exc}, using fallback"
        )

    # Fallback: summarize the topics discussed from user messages
    topics = []
    for m in early_turns:
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str) and content.strip():
                topics.append(content.strip()[:80])
        elif m.get("role") == "tool":
            # Mark that tools were executed (tool name is not embedded in this format)
            content_raw = m.get("content", "")
            if content_raw:
                topics.append("[tool execution step]")
    unique_topics = list(dict.fromkeys(topics))
    topic_str = "; ".join(unique_topics[:6]) if unique_topics else "various operations"
    return f"Earlier conversation covered: {topic_str}."
