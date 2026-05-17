"""
Captures live desktop state every N seconds. Caches in memory, pushes to write queue.
"""

import json
import logging
import threading
import time

from settings import STATE_MONITOR_INTERVAL

logger = logging.getLogger(__name__)
_latest_snapshot = {}
_lock = threading.Lock()


# â”€â”€ Background task snapshot â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_bg_lock = threading.Lock()
_bg_processes_imported = False
_bg_processes_ref = None


def _ensure_bg_imported():
    """Thread-safe lazy import using double-checked locking."""
    global _bg_processes_imported, _bg_processes_ref
    if _bg_processes_imported:
        return
    with _bg_lock:
        if _bg_processes_imported:
            return
        try:
            from tools.system.execute_code import _bg_processes
            _bg_processes_ref = _bg_processes
        except ImportError:
            _bg_processes_ref = {}
        _bg_processes_imported = True


def _background_tasks() -> list[dict]:
    global _bg_processes_imported, _bg_processes_ref
    _ensure_bg_imported()
    d = _bg_processes_ref
    if not d:
        return []
    now = time.time()
    result = []
    with _bg_lock:
        items = list(d.items())
    for pid, info in items:
        p = info.get("proc")
        rc = p.poll() if p else None
        done = rc is not None
        result.append({
            "pid": pid,
            "running": not done,
            "returncode": rc,
            "elapsed_seconds": round(now - info.get("started", now), 1),
            "language": info.get("language", "?"),
            "code_preview": info.get("code", "")[:80],
        })
    return result


# â”€â”€ System process filter â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_SYSTEM_PROCS = {
    "SystemSettings.exe", "ShellExperienceHost.exe", "SearchHost.exe",
    "SearchUI.exe", "SearchIndexer.exe", "TextInputHost.exe", "LockApp.exe",
    "RuntimeBroker.exe", "dllhost.exe", "svchost.exe", "conhost.exe",
    "ctfmon.exe", "SecurityHealthSystray.exe", "OneDrive.exe",
}


# â”€â”€ Window enumeration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_raw_windows() -> list[dict]:
    import win32gui, win32process, psutil
    results = []
    def callback(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd): return
            if win32gui.GetParent(hwnd) != 0: return
            rect = win32gui.GetWindowRect(hwnd)
            if rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0: return
            title = win32gui.GetWindowText(hwnd).strip()
            if not title: return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc_name = psutil.Process(pid).name() if pid else "unknown"
            results.append({"hwnd": int(hwnd), "title": title, "process": proc_name, "pid": pid})
        except Exception:
            pass
    win32gui.EnumWindows(callback, None)
    return results


def _get_taskbar_apps() -> list[dict]:
    seen_titles = set()
    apps = []
    for w in _get_raw_windows():
        if w["process"] in _SYSTEM_PROCS: continue
        if w["title"] in seen_titles: continue
        seen_titles.add(w["title"])
        apps.append(w)
    return apps


# â”€â”€ Clipboard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_clipboard(max_chars: int = 500) -> str:
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                return str(data)[:max_chars] if data else ""
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        pass
    return ""


# â”€â”€ Public API: full desktop snapshot â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def read_pc_state(**kwargs) -> dict:
    try:
        import win32gui, win32process, psutil
        apps = _get_taskbar_apps()
        raw_windows = _get_raw_windows()
        focused_title = ""
        focused_proc = ""
        try:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                focused_title = win32gui.GetWindowText(hwnd)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                focused_proc = psutil.Process(pid).name()
        except Exception:
            pass
        return {
            "success": True,
            "windows": apps,
            "processes": list({a["process"] for a in apps}),
            "app_count": len(apps),
            "window_count": len(raw_windows),
            "focused_window": focused_title,
            "focused_process": focused_proc,
            "clipboard": _get_clipboard(),
            "background_tasks": _background_tasks(),
        }
    except Exception as e:
        logger.error(f"read_pc_state error: {e}", exc_info=True)
        return {"success": False, "error": f"Internal error: {str(e)}"}


# â”€â”€ Periodic capture loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def capture_state() -> dict:
    try:
        user_apps = _get_taskbar_apps()
        raw_windows = _get_raw_windows()
        import win32gui, win32process, psutil
        focused = ""
        focused_proc = ""
        try:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                focused = win32gui.GetWindowText(hwnd)
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    focused_proc = psutil.Process(pid).name()
                except Exception:
                    focused_proc = "unknown"
        except Exception:
            pass
        return {
            "captured_at": time.time(),
            "windows_json": json.dumps(user_apps[:25]),
            "processes_json": json.dumps(list({w["process"] for w in user_apps})[:20]),
            "focused_app": focused,
            "focused_process": focused_proc,
            "app_count": len(user_apps),
            "window_count": len(raw_windows),
            "clipboard": _get_clipboard(),
        }
    except Exception as e:
        logger.error(f"capture_state error: {e}", exc_info=True)
        # Return minimal structure with required fields as empty JSON strings
        return {
            "captured_at": time.time(),
            "windows_json": json.dumps([]),
            "processes_json": json.dumps([]),
            "focused_app": "",
            "focused_process": "",
            "app_count": 0,
            "window_count": 0,
            "clipboard": _get_clipboard(),
        }

def monitor_loop(writer, stop_event):
    global _latest_snapshot
    while not stop_event.is_set():
        try:
            state = capture_state()
            with _lock:
                _latest_snapshot = state
            writer.push("state_snapshots", [state])
        except Exception as e:
            logger.error(f"State monitor error: {e}")
        stop_event.wait(STATE_MONITOR_INTERVAL)


def get_latest() -> dict:
    with _lock:
        snap = dict(_latest_snapshot)
    if "windows_json" in snap and isinstance(snap["windows_json"], str):
        try:
            snap["windows"] = json.loads(snap["windows_json"])
        except Exception:
            snap["windows"] = []
    if "processes_json" in snap and isinstance(snap["processes_json"], str):
        try:
            snap["processes"] = json.loads(snap["processes_json"])
        except Exception:
            snap["processes"] = []
    return snap

