"""
Piper TTS — local offline fallback for output/tts.py.

Used automatically when:
  - settings.TTS_ENGINE == "piper", or
  - Edge TTS synthesis fails (network error, timeout, import error).

Piper pipes text via stdin, renders raw PCM to stdout, and plays through the
default audio device.  Requires piper.exe (or piper on Linux/macOS) plus the
matching .onnx model and .onnx.json config files.

This module is intentionally self-contained — it does NOT touch IS_SPEAKING.
The IS_SPEAKING flag lifecycle is managed entirely by the caller (output/tts.py).
"""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

from settings import PIPER_BINARY, PIPER_MODEL, PIPER_MODEL_JSON

logger = logging.getLogger(__name__)

# Resolved binary path is cached after the first successful lookup.
_piper_path: str | None = None


# ── Public API ────────────────────────────────────────────────────────────────


def speak_piper(text: str, blocking: bool = True) -> bool:
    """
    Speak *text* via the local Piper TTS binary.

    Piper reads UTF-8 text from stdin and writes raw PCM audio (16-bit signed,
    mono, 22 050 Hz by default for the lessac model) to stdout or directly to
    the audio device depending on the flags passed.

    Args:
        text:     The string to synthesise.
        blocking: If True (default) wait for the subprocess to exit before
                  returning.  If False, return immediately after launching.

    Returns:
        True  — subprocess launched successfully (and finished if blocking=True).
        False — binary not found, or subprocess raised an exception.
    """
    global _piper_path

    piper = _resolve_piper()
    if piper is None:
        return False

    try:
        cmd = _build_cmd(piper)
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_no_window_flag(),
        )

        # Write text then close stdin so Piper knows it has received all input.
        proc.stdin.write(text.encode("utf-8"))  # type: ignore[union-attr]
        proc.stdin.close()  # type: ignore[union-attr]

        if blocking:
            proc.wait(timeout=60)
        else:
            # Detach: close stdin so the process can finish, then wait briefly
            # to collect the zombie instead of leaving it orphaned.
            def _reap():
                try:
                    proc.wait(timeout=30)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=5)
                    except Exception:
                        pass
            threading.Thread(target=_reap, daemon=True).start()

        logger.info(f"TTS(piper): spoke {len(text)} chars")
        return True

    except FileNotFoundError:
        logger.error(
            f"TTS(piper): binary not found at '{piper}'. "
            "Install Piper or set TTS_ENGINE=edge in .env"
        )
        _piper_path = None  # Reset so next call retries discovery
        return False

    except subprocess.TimeoutExpired:
        logger.error("TTS(piper): subprocess timed out — killing")
        try:
            proc.kill()
        except Exception:
            pass
        return False

    except Exception as exc:
        logger.error(f"TTS(piper): unexpected error — {exc}", exc_info=True)
        return False


# ── Internal helpers ──────────────────────────────────────────────────────────


def _resolve_piper() -> str | None:
    """
    Return the absolute path to the Piper binary, or None if not found.

    Search order:
      1. Cached result from a previous successful call.
      2. Exact path from settings (PIPER_BINARY / PIPER_EXE env var).
      3. ~/piper/<binary>
      4. Platform-specific program directory (Windows: Program Files, Linux/macOS: /opt)
      5. PATH lookup via shutil.which
    """
    global _piper_path
    import shutil
    import platform

    if _piper_path and Path(_piper_path).exists():
        return _piper_path

    candidates = [
        PIPER_BINARY,
        str(Path.home() / "piper" / PIPER_BINARY),
    ]
    
    # Add platform-specific program directory
    system = platform.system()
    if system == "Windows":
        candidates.append(str(Path("C:/Program Files/piper") / PIPER_BINARY))
    elif system in ("Linux", "Darwin"):
        candidates.append(str(Path("/opt/piper") / PIPER_BINARY.replace(".exe", "")))
    
    # Try PATH lookup as final fallback
    piper_name = PIPER_BINARY.replace(".exe", "") if system != "Windows" else PIPER_BINARY
    which_path = shutil.which(piper_name)
    if which_path:
        candidates.append(which_path)

    for candidate in candidates:
        if Path(candidate).exists():
            _piper_path = candidate
            logger.debug(f"TTS(piper): binary found at '{candidate}'")
            return candidate

    logger.warning(
        f"TTS(piper): binary '{PIPER_BINARY}' not found in any of: "
        + ", ".join(candidates)
    )
    return None


def _build_cmd(piper_exe: str) -> list[str]:
    """Build the Piper subprocess command line."""
    return [
        piper_exe,
        "--model",
        str(Path(PIPER_MODEL).resolve()),
        "--config",
        str(Path(PIPER_MODEL_JSON).resolve()),
        "--output-raw",
    ]


def _no_window_flag() -> int:
    """Return CREATE_NO_WINDOW on Windows, 0 on other platforms."""
    try:
        return subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    except AttributeError:
        return 0
