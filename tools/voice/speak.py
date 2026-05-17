"""
Speak tool — lets the LLM explicitly trigger text-to-speech mid-task.

This is distinct from the automatic TTS the orchestrator applies to the
final response. Use this tool when Jarvis should narrate progress, read
something aloud, or communicate verbally without ending the task loop.

Args
----
text      — the string to speak (required)
blocking  — wait for audio to finish before returning (default True)
            set False to speak and immediately continue working
"""

import logging

logger = logging.getLogger(__name__)


def speak(text: str, blocking: bool = True) -> dict:
    """
    Speak *text* aloud via the configured TTS engine (Edge TTS / Piper).

    Returns {success, text, blocking} or {success: False, error}.
    """
    if not text or not text.strip():
        return {"success": False, "error": "No text provided to speak."}

    text = text.strip()

    try:
        from output.tts import speak as _tts_speak

        ok = _tts_speak(text, blocking=blocking)
        if ok:
            logger.info(f"speak tool: spoke {len(text)} chars (blocking={blocking})")
            return {
                "success": True,
                "text": text,
                "blocking": blocking,
                "chars": len(text),
            }
        else:
            return {
                "success": False,
                "error": "TTS engine failed or is disabled — check TTS_ENABLED in settings.",
            }

    except Exception as e:
        logger.error(f"speak tool: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
