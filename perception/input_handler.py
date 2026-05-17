"""
Routes voice/text/scheduled inputs to the orchestrator.
Checks IS_SPEAKING flag before triggering STT.
"""

import logging
import threading

import settings
from perception import stt, wake_word

logger = logging.getLogger(__name__)


class InputHandler:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        # Prevents multiple concurrent wake-word → STT → route pipelines.
        # Without this, each wake-word detection during a long STT timeout
        # spawns a new stt.listen() call; when the user next speaks, all of
        # them hear it simultaneously and route the same command N times.
        self._wake_busy = threading.Event()
        wake_word.set_wake_callback(self._on_wake)
        logger.info("InputHandler initialized")

    def _on_wake(self, wake_word: str = ""):
        """Called when wake word detected."""
        # Re-entrant guard: if already in the STT → route pipeline, drop trigger.
        if self._wake_busy.is_set():
            logger.debug("Wake word ignored — already processing a command")
            return

        # Don't fight the listen tool for mic access.
        if settings.STT_EXCLUSIVE.is_set():
            logger.debug("Wake word ignored — STT_EXCLUSIVE held by listen tool")
            return

        self._wake_busy.set()
        try:
            logger.info("Wake word triggered — listening...")
            text = stt.listen(timeout=8.0)
            if text:
                self.route(text, source="voice")
        finally:
            self._wake_busy.clear()

    def route(self, user_input: str, source: str = "text"):
        """Route input to orchestrator and handle response."""
        if not user_input.strip():
            return
        logger.info(f"InputHandler.route [{source}]: '{user_input}'")
        try:
            response = self.orchestrator.handle(user_input)
            self._output(response)
        except Exception as e:
            logger.error(f"InputHandler error: {e}")
            self._output(f"Error: {e}")

    def _output(self, text: str):
        """Send response to TTS and/or CLI."""
        from output.formatter import format_for_tts
        from output.tts import speak

        formatted = format_for_tts(text)
        if formatted:
            speak(formatted, blocking=False)
        print(f"\nJARVIS: {text}")

    def start_listening(self):
        """Start wake word listener (background thread)."""
        wake_word.start()
        logger.info("InputHandler listening for wake word")

    def stop(self):
        wake_word.stop()
