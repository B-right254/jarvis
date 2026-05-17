"""
Unified SystemState — continuously updated shared desktop state.

Every component reads from this instead of calling OS APIs repeatedly.
Updated after every tool call by the orchestrator.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)


class SystemState:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = {
            "active_window": "",
            "active_window_process": "",
            "focused_element": "",
            "screen_text": "",
            "mouse_position": (0, 0),
            "cpu_percent": 0.0,
            "ram_percent": 0.0,
            "ram_free_gb": 0.0,
            "disk_percent": 0.0,
            "disk_free_gb": 0.0,
            "battery_percent": None,
            "battery_plugged": None,
            "last_action": "",
            "last_result": {},
            "timestamp": "",
        }
        self.refresh_from_os()

    def update(self, tool_name: str, args: dict, result: dict):
        raw_data = result.get("data", {})
        now = result.get("timestamp", "")
        with self._lock:
            self._state["last_action"] = tool_name
            self._state["last_args"] = args
            self._state["last_result"] = result
            self._state["timestamp"] = now

            if "active_window" in raw_data:
                self._state["active_window"] = str(raw_data["active_window"])
            if "title" in raw_data:
                self._state["active_window"] = raw_data["title"]
            if "process" in raw_data:
                self._state["active_window_process"] = str(raw_data["process"])
            if "text" in raw_data:
                self._state["screen_text"] = raw_data["text"][:2000]
            if "cpu_percent" in raw_data:
                self._state["cpu_percent"] = raw_data["cpu_percent"]
            if "ram_percent" in raw_data:
                self._state["ram_percent"] = raw_data["ram_percent"]
            if "ram_free_gb" in raw_data:
                self._state["ram_free_gb"] = raw_data["ram_free_gb"]
            if "disk_percent" in raw_data:
                self._state["disk_percent"] = raw_data["disk_percent"]
            if "disk_free_gb" in raw_data:
                self._state["disk_free_gb"] = raw_data["disk_free_gb"]
            if "battery_percent" in raw_data:
                self._state["battery_percent"] = raw_data["battery_percent"]
            if "battery_plugged" in raw_data:
                self._state["battery_plugged"] = raw_data["battery_plugged"]
            if "elements" in raw_data:
                self._state["focused_element"] = str(raw_data["elements"][:3])

    def get(self, key: str, default=None):
        with self._lock:
            return self._state.get(key, default)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def refresh_from_os(self):
        """Pull live OS state for fields that change without tool calls."""
        try:
            import pygetwindow as gw
            import pyautogui
        except ImportError:
            return
        with self._lock:
            try:
                win = gw.getActiveWindow()
                if win:
                    self._state["active_window"] = win.title
            except Exception:
                pass
            try:
                mx, my = pyautogui.position()
                self._state["mouse_position"] = (mx, my)
            except Exception:
                pass