"""
listen — on-demand speech capture.

Allows Jarvis to ask a spoken question mid-task and receive a spoken answer
without requiring the user to type.  Coordinates with the continuous wake-word
listener via the ``STT_EXCLUSIVE`` event so the two never fight over the mic.

Lifecycle
---------
1. Optionally speaks a prompt via TTS (blocking, so the user hears the question
   before the mic opens).
2. Sets ``settings.STT_EXCLUSIVE`` → the wake-word listener pauses.
3. Calls ``perception.stt.transcribe_once()`` to capture one utterance.
4. Clears ``settings.STT_EXCLUSIVE`` → wake-word listener resumes.
5. Returns ``{"success": True, "text": <str>, "heard": <bool>}``.

The finally-block guarantees STT_EXCLUSIVE is always cleared, even on error.
"""

from __future__ import annotations

import logging

import settings

logger = logging.getLogger(__name__)


def listen(
    prompt: str | None = None,
    timeout_seconds: int = 10,
    speak_prompt: bool = True,
) -> dict:
    """
    Capture one utterance from the microphone and return the transcription.

    Parameters
    ----------
    prompt : str | None
        If given, speak this text aloud before opening the mic so the user
        knows they should say something.
    timeout_seconds : int
        Seconds to wait for speech before giving up (default 10).
    speak_prompt : bool
        Whether to speak the prompt via TTS (default True).  Set False if
        you've already notified the user by other means.

    Returns
    -------
    dict
        ``{"success": True, "text": <str>, "heard": <bool>}``
        ``text`` is empty string when nothing was heard.
    """
    # ── optional spoken prompt ────────────────────────────────────────────────
    if prompt and speak_prompt:
        try:
            from output.tts import speak
            speak(prompt, blocking=True)
        except Exception as exc:
            logger.warning(f"listen: TTS prompt failed — {exc}")

    # ── exclusive mic acquisition ─────────────────────────────────────────────
    logger.info(f"listen: acquiring mic (timeout={timeout_seconds}s)")
    settings.STT_EXCLUSIVE.set()

    try:
        from perception.stt import transcribe_once
        text = transcribe_once(timeout=float(timeout_seconds))
        heard = bool(text and text.strip())
        if heard:
            logger.info(f"listen: heard '{text}'")
        else:
            logger.info("listen: no speech captured")
        return {"success": True, "text": text or "", "heard": heard}

    except Exception as exc:
        logger.error(f"listen: error during capture — {exc}")
        return {"success": False, "error": str(exc), "text": "", "heard": False}

    finally:
        # Always release the mic, even on exception
        settings.STT_EXCLUSIVE.clear()
        logger.debug("listen: mic released")
