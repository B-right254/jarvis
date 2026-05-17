"""
Thread-safe console I/O helpers for JARVIS.

Problem
-------
background threads (indexer, file-scanner, skill-embedder …) can call the
Python logging system at any time.  When the main thread is blocked inside
``input()`` waiting for the user, the logging StreamHandler writes to the
same stdout stream, producing garbage like:

    > 2026-05-08 09:55:43 [INFO] indexer.file_scanner: File scan pushed …

Solution
--------
``PromptAwareStreamHandler`` checks a shared ``prompt_active`` event before
emitting.  While the prompt is active it:
  1. Moves the cursor to column 0 and blanks the current line.
  2. Prints the log record on the now-clean line.
  3. Reprints ``> `` so the user can keep typing.

``cli_input()`` is a drop-in replacement for ``input()`` that arms the event
before blocking and disarms it once the user presses Enter.
"""

import logging
import shutil
import threading

# ---------------------------------------------------------------------------
# Shared flag: True while the CLI is blocked inside input()
# ---------------------------------------------------------------------------
prompt_active: threading.Event = threading.Event()


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class PromptAwareStreamHandler(logging.StreamHandler):
    """
    StreamHandler that cooperates with the interactive ``> `` prompt.

    When a background thread emits a log record while the user is sitting at
    the prompt this handler:
      1. Moves to the start of the current line and blanks it.
      2. Prints the log record cleanly.
      3. Reprints ``> `` so the user can continue typing.

    When the prompt is not active (startup, processing a command …) records
    are printed normally with a trailing newline.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self.lock:
                self._write_msg(msg)
        except Exception:
            self.handleError(record)

    def _write_msg(self, msg: str) -> None:
        """Write *msg* to the stream, falling back to ASCII-safe output on
        UnicodeEncodeError so the Windows CP1252 console never crashes."""
        cols = shutil.get_terminal_size((80, 24)).columns
        active = prompt_active.is_set()
        try:
            if active:
                self.stream.write(f"\r{' ' * cols}\r{msg}\n> ")
            else:
                self.stream.write(msg + "\n")
            self.stream.flush()
        except UnicodeEncodeError:
            # Strip / replace characters the console codec can't handle,
            # then retry.  This is the last-resort path — normally stdout
            # is reconfigured to UTF-8 with errors='replace' at startup.
            enc = getattr(self.stream, "encoding", "ascii") or "ascii"
            safe = msg.encode(enc, errors="replace").decode(enc)
            if active:
                self.stream.write(f"\r{' ' * cols}\r{safe}\n> ")
            else:
                self.stream.write(safe + "\n")
            self.stream.flush()


# ---------------------------------------------------------------------------
# Input helper
# ---------------------------------------------------------------------------


def cli_input(prompt_str: str = "\n> ") -> str:
    """
    Drop-in replacement for ``input()`` that arms ``prompt_active`` while
    blocking so ``PromptAwareStreamHandler`` can safely clear the line.

    Usage::

        from core.console import cli_input
        user_input = cli_input()
    """
    prompt_active.set()
    try:
        return input(prompt_str)
    finally:
        prompt_active.clear()
