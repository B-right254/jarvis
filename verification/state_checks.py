"""
Tier 1: Deterministic OS-level verification. <10ms.
"""

import logging

import psutil
import win32gui

logger = logging.getLogger(__name__)


def verify_process_running(name: str) -> bool:
    """Return True if any running process name contains `name` (case-insensitive)."""
    return any(name.lower() in p.name().lower() for p in psutil.process_iter(["name"]))


def verify_window_visible(title: str) -> bool:
    """
    Return True if any visible window title contains `title` (case-insensitive).

    win32gui.EnumWindows() always returns None in Python — the callback's
    return value only controls enumeration flow (False stops it), it is NOT
    propagated back to the caller.  The correct pattern is to mutate a
    container passed through the extra parameter and inspect it afterwards.
    """
    found = [False]
    search_title = title.lower().strip()

    def _cb(hwnd, _param):
        try:
            if not hwnd or not win32gui.IsWindow(hwnd):
                return 1
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd).lower()
                if search_title in t:
                    found[0] = True
                    return 0  # stop enumeration early
        except Exception:
            pass
        return 1  # keep going

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception as exc:
        # EnumWindows raises when the callback returns False — that's normal.
        # Any other exception is logged.
        if found[0]:
            pass  # expected early-exit exception
        else:
            logger.debug(f"verify_window_visible unexpected error: {exc}")

    return found[0]
