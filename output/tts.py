"""
Text-to-Speech — Edge TTS primary, pyttsx3 fallback (cross-platform).

Engine selection (settings.TTS_ENGINE):
  "edge"  — Microsoft Edge TTS via edge-tts (requires internet, zero install).
            Audio is synthesised to a temp MP3 then played through pygame or
            directly via system audio APIs. Falls back to pyttsx3 on failure.
  "piper" — Local Piper binary (offline, needs piper.exe + model files).
            Falls back to pyttsx3 if Piper is not available.
  any other value falls back to pyttsx3 as well.

IS_SPEAKING is set to True on *entry* (before any try/except) so the STT
listener is muted for the entire duration of speech synthesis + playback.
It is always cleared in the finally block — even on error — to guarantee
the mic is never permanently silenced.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import threading
from pathlib import Path

import settings

logger = logging.getLogger(__name__)

# ── Lazy pygame mixer initialisation ──────────────────────────────────────────
_mixer_ready: bool = False

# Files queued for deletion after non-blocking playback finishes.
# _speak_edge appends the path; _wait_and_clear drains the queue.
# Protected by _tmp_cleanup_lock for thread safety.
_tmp_cleanup_queue: list[str] = []
_tmp_cleanup_lock = threading.Lock()


def _init_mixer() -> bool:
    """Initialise pygame.mixer on first use. Returns True on success."""
    global _mixer_ready
    if _mixer_ready:
        return True
    try:
        os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
        # Try DirectSound first on Windows to avoid WASAPI issues
        if sys.platform == "win32":
            os.environ["SDL_AUDIODRIVER"] = "directsound"
        import pygame  # noqa: PLC0415

        if not pygame.get_init():
            pygame.init()
        
        # Try multiple audio configurations for better Windows/Linux compatibility
        _configs = [
            {'frequency': 44100, 'size': -16, 'channels': 2, 'buffer': 512},
            {'frequency': 44100, 'size': 16, 'channels': 2, 'buffer': 512},
            {'frequency': 22050, 'size': 16, 'channels': 2, 'buffer': 4096},
            {'frequency': 48000, 'size': -16, 'channels': 2, 'buffer': 1024},
        ]
        
        for config in _configs:
            try:
                pygame.mixer.init(**config)
                _mixer_ready = True
                logger.debug(f"TTS: pygame mixer initialised with {config}")
                return True
            except pygame.error:
                continue
        
        # If all configs fail, raise to trigger fallback
        raise pygame.error("No audio configuration succeeded")
        
    except Exception as exc:
        logger.warning(f"TTS: pygame mixer init failed — {exc}")
        return False


# ── Public API ─────────────────────────────────────────────────────────────────


def speak(text: str, blocking: bool = True) -> bool:
    """
    Convert *text* to speech and play it through the default audio device.

    Args:
        text:     The string to speak.  Empty / whitespace-only strings are
                  silently ignored (returns True).
        blocking: Wait for playback to finish before returning (default True).
                  When False the function returns as soon as playback starts;
                  IS_SPEAKING will be cleared by a background thread.

    Returns:
        True  — audio was synthesised and playback started (or was skipped
                because TTS is disabled or text was empty).
        False — synthesis or playback failed (error is logged).
    """
    # Fast exits — don't touch IS_SPEAKING so we don't accidentally mute STT
    if not settings.TTS_ENABLED:
        logger.debug("TTS: disabled in settings — skipping")
        return True

    text = text.strip()
    if not text:
        logger.debug("TTS: empty text — skipping")
        return True

    # ── Mute STT immediately on entry, before ANY try/except ─────────────────
    settings.IS_SPEAKING.set()

    try:
        engine = settings.TTS_ENGINE.lower().strip()

        if engine == "edge":
            return _speak_edge(text, blocking)
        else:
            # "piper" or any unrecognised value → local fallback
            from output.tts_piper import speak_piper  # noqa: PLC0415

            return speak_piper(text, blocking)

    except Exception as exc:
        logger.error(f"TTS: unexpected error in speak() — {exc}", exc_info=True)
        return False

    finally:
        # ── Always restore STT after an acoustic drain delay ──────────────────
        if blocking:
            # Wait for audio to dissipate using non-blocking pygame clock instead of time.sleep
            import pygame  # noqa: PLC0415
            _dissipate_ticks = 16  # ~0.8s at 20Hz
            _clock = pygame.time.Clock()
            for _ in range(_dissipate_ticks):
                _clock.tick(20)
            settings.IS_SPEAKING.clear()
        else:
            # Non-blocking: background thread waits for playback to finish,
            # cleans up the temp file, then clears IS_SPEAKING.
            # DO NOT unload/delete the file here — audio would cut mid-sentence.
            import threading  # noqa: PLC0415

            def _wait_and_clear():
                try:
                    import pygame  # noqa: PLC0415

                    while pygame.mixer.music.get_busy():
                        pygame.time.Clock().tick(20)
                    # Unload so Windows releases the file handle, then delete queued temps.
                    try:
                        pygame.mixer.music.unload()
                    except Exception:
                        pass
                    import threading as _thr
                    with _thr.Lock():
                        for p in list(_tmp_cleanup_queue):
                            try:
                                Path(p).unlink(missing_ok=True)
                                _tmp_cleanup_queue.remove(p)
                            except Exception:
                                pass
                    # Non-blocking wait using pygame clock instead of time.sleep
                    _clock = pygame.time.Clock()
                    for _ in range(16):  # ~0.8s at 20Hz
                        _clock.tick(20)
                except Exception:
                    pass
                finally:
                    settings.IS_SPEAKING.clear()

            threading.Thread(target=_wait_and_clear, daemon=True, name="tts-clear").start()


# ── Edge TTS implementation ───────────────────────────────────────────────────


def _speak_edge(text: str, blocking: bool) -> bool:
    """
    Synthesise *text* with Microsoft Edge TTS and play via pygame or pyttsx3.

    Flow:
        1. Run async edge_tts.Communicate.save() to write an MP3 to a temp file.
        2. Try to load the MP3 with pygame.mixer.music.
        3. If pygame fails, fall back to pyttsx3 for audio playback.
        4. Play (blocking or non-blocking).
        5. Delete the temp file after playback.

    Falls back to pyttsx3 on any pygame failure.
    """
    try:
        import edge_tts  # noqa: PLC0415
    except ImportError:
        logger.warning("TTS: edge-tts not installed — falling back to pyttsx3")
        return _fallback_pyttsx3(text, blocking)

    if not _init_mixer():
        logger.warning("TTS: pygame unavailable — falling back to pyttsx3")
        return _fallback_pyttsx3(text, blocking)

    tmp_path: str | None = None
    try:
        # ── 1. Synthesise to temp file ─────────────────────────────────────
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp3", prefix="jarvis_tts_")
        os.close(tmp_fd)  # edge-tts opens the file itself; close the fd first

        communicate = edge_tts.Communicate(
            text=text,
            voice=settings.EDGE_TTS_VOICE,
            rate=settings.EDGE_TTS_RATE,
            volume=settings.EDGE_TTS_VOLUME,
            pitch=settings.EDGE_TTS_PITCH,
        )

        # Run edge-tts in a dedicated thread with its own event loop to avoid
        # deadlocking when called from a thread that already has a running loop.
        import concurrent.futures

        def _run_edge_synthesis():
            import asyncio
            asyncio.run(
                asyncio.wait_for(
                    communicate.save(tmp_path),
                    timeout=settings.EDGE_TTS_TIMEOUT,
                )
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _tts_pool:
            _tts_future = _tts_pool.submit(_run_edge_synthesis)
            _tts_future.result(timeout=settings.EDGE_TTS_TIMEOUT + 10)

        logger.debug(f"TTS(edge): synthesised {len(text)} chars → {tmp_path}")

        # ── 2 & 3. Load and play ──────────────────────────────────────────
        import pygame  # noqa: PLC0415

        pygame.mixer.music.load(tmp_path)
        pygame.mixer.music.play()

        if blocking:
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(20)
            # Give mixer a moment to fully flush using non-blocking clock tick
            _clock = pygame.time.Clock()
            for _ in range(2):  # ~0.1s at 20Hz
                _clock.tick(20)

        logger.info(f"TTS(edge): spoke {len(text)} chars via {settings.EDGE_TTS_VOICE}")
        return True

    except asyncio.TimeoutError:
        logger.error(
            f"TTS(edge): synthesis timed out after {settings.EDGE_TTS_TIMEOUT}s "
            "— falling back to pyttsx3"
        )
        return _fallback_pyttsx3(text, blocking)

    except Exception as exc:
        logger.error(f"TTS(edge): failed — {exc} — falling back to pyttsx3")
        return _fallback_pyttsx3(text, blocking)

    finally:
        # ── 4. Clean up temp file ──────────────────────────────────────────────
        # Blocking: playback finished, safe to unload and delete now.
        # Non-blocking: queue the path for the tts-clear thread to delete
        # after get_busy() returns False — deleting here cuts audio mid-sentence.
        if blocking and tmp_path:
            try:
                import pygame  # noqa: PLC0415
                pygame.mixer.music.unload()
            except Exception:
                pass
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
        elif tmp_path:
            with _tmp_cleanup_lock:
                _tmp_cleanup_queue.append(tmp_path)


# ── Cross-platform fallback helper (pyttsx3) ──────────────────────────────────


def _fallback_pyttsx3(text: str, blocking: bool) -> bool:
    """
    Use pyttsx3 for cross-platform TTS fallback.
    
    This works on Windows (SAPI5), macOS (nsss), and Linux (espeak).
    Does not require pygame or any specific audio hardware configuration.
    """
    logger.info("TTS: using pyttsx3 fallback (cross-platform)")
    try:
        import pyttsx3  # noqa: PLC0415
        
        engine = pyttsx3.init()
        
        # Configure voice properties from settings if available
        voices = engine.getProperty('voices')
        if voices and hasattr(settings, 'TTS_VOICE') and settings.TTS_VOICE:
            # Try to find a matching voice
            for voice in voices:
                if settings.TTS_VOICE.lower() in voice.name.lower() or \
                   settings.TTS_VOICE.lower() in voice.id.lower():
                    engine.setProperty('voice', voice.id)
                    break
        
        if hasattr(settings, 'TTS_RATE') and settings.TTS_RATE:
            engine.setProperty('rate', settings.TTS_RATE)
        if hasattr(settings, 'TTS_VOLUME') and settings.TTS_VOLUME:
            engine.setProperty('volume', min(settings.TTS_VOLUME / 100.0, 1.0))
        
        engine.say(text)
        if blocking:
            engine.runAndWait()
        else:
            # Non-blocking: start in a thread
            import threading
            threading.Thread(target=engine.runAndWait, daemon=True).start()
        
        return True
    except Exception as exc:
        logger.error(f"TTS(pyttsx3 fallback): failed — {exc}")
        return False


def _fallback_piper(text: str, blocking: bool) -> bool:
    """Delegate to the Piper module, then fall back to pyttsx3 on failure."""
    logger.info("TTS: trying Piper, will fall back to pyttsx3")
    try:
        from output.tts_piper import speak_piper  # noqa: PLC0415

        result = speak_piper(text, blocking)
        if not result:
            logger.info("TTS: Piper returned False, falling back to pyttsx3")
            return _fallback_pyttsx3(text, blocking)
        return result
    except Exception as exc:
        logger.warning(f"TTS(piper): failed ({exc}), falling back to pyttsx3")
        return _fallback_pyttsx3(text, blocking)
