"""
Ambient system-health monitor — background daemon thread.

Simplified: exponential backoff, value-change thresholds, and per-event
suppression logic removed. Alerts fire at a simple fixed cooldown interval
to prevent spam while keeping the user informed of persistent conditions.
"""

import logging
import platform
import threading
import time

logger = logging.getLogger(__name__)

try:
    import psutil as _psutil
    _psutil_available = True
except ImportError:
    _psutil = None
    _psutil_available = False
    logger.warning("ambient_monitor: psutil not installed — hardware monitoring disabled.")

try:
    from settings import AMBIENT_MONITORING, BATTERY_CRITICAL_THRESHOLD, BATTERY_WARN_THRESHOLD, CPU_SPIKE_DURATION, CPU_SPIKE_THRESHOLD, DISK_WARN_THRESHOLD, MEMORY_WARN_THRESHOLD, MONITOR_INTERVAL
except ImportError:
    AMBIENT_MONITORING = True
    BATTERY_WARN_THRESHOLD = 20
    BATTERY_CRITICAL_THRESHOLD = 10
    CPU_SPIKE_THRESHOLD = 90
    CPU_SPIKE_DURATION = 30
    MEMORY_WARN_THRESHOLD = 85
    DISK_WARN_THRESHOLD = 92
    MONITOR_INTERVAL = 15

def _notify_user(message: str, urgency: str = "normal") -> dict:
    logger.warning(f"ambient_monitor [{urgency.upper()}]: {message}")
    return {"success": False, "reason": "notify_user_unavailable"}

_COOLDOWN = 600  # 10 minutes between repeat alerts

_stop_event: threading.Event = threading.Event()
_thread: "threading.Thread | None" = None
_cpu_spike_start: "float | None" = None
_last_alert: dict[str, float] = {}


def start() -> dict:
    global _thread
    if not AMBIENT_MONITORING:
        return {"success": False, "reason": "disabled_by_settings"}
    if not _psutil_available:
        return {"success": False, "reason": "psutil_not_installed"}
    if _thread and _thread.is_alive():
        return {"success": True, "reason": "already_running"}
    _stop_event.clear()
    _thread = threading.Thread(target=_monitor_loop, daemon=True, name="ambient-monitor")
    _thread.start()
    return {"success": True}


def stop() -> dict:
    global _thread
    _stop_event.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=5)
    return {"success": True}


def _alert(event_key: str, message: str, urgency: str):
    now = time.time()
    if now - _last_alert.get(event_key, 0) < _COOLDOWN:
        return
    try:
        _notify_user(message, urgency)
    except Exception as exc:
        logger.error(f"ambient_monitor: notify_user raised: {exc}")
    _last_alert[event_key] = now
    logger.info(f"ambient_monitor: alert [{urgency}] — {message}")


def _check_battery():
    if _psutil is None:
        return
    battery = _psutil.sensors_battery()
    if battery is None:
        return
    pct = battery.percent
    plugged = bool(battery.power_plugged)
    if plugged:
        _last_alert.pop("battery_critical", None)
        _last_alert.pop("battery_warn", None)
        return
    if pct <= BATTERY_CRITICAL_THRESHOLD:
        _alert("battery_critical", f"Battery critically low: {pct:.0f}% — plug in immediately!", "high")
    elif pct <= BATTERY_WARN_THRESHOLD:
        _alert("battery_warn", f"Battery low: {pct:.0f}% remaining.", "normal")


def _check_cpu(now: float):
    global _cpu_spike_start
    if _psutil is None:
        return
    cpu_pct = _psutil.cpu_percent(interval=None)
    if cpu_pct >= CPU_SPIKE_THRESHOLD:
        if _cpu_spike_start is None:
            _cpu_spike_start = now
        elif now - _cpu_spike_start >= CPU_SPIKE_DURATION:
            _alert("cpu_spike", f"CPU at {cpu_pct:.0f}% for {int(now - _cpu_spike_start)}s", "high")
    else:
        _cpu_spike_start = None


def _check_memory():
    if _psutil is None:
        return
    mem = _psutil.virtual_memory()
    pct = mem.percent
    if pct < MEMORY_WARN_THRESHOLD:
        _last_alert.pop("memory_warn", None)
        return
    free_mb = mem.available // (1024 ** 2)
    urgency = "high" if pct >= 95 else "normal"
    _alert("memory_warn", f"Memory at {pct:.0f}% ({free_mb} MB free).", urgency)


def _check_disk():
    if _psutil is None:
        return
    root = "C:\\" if platform.system() == "Windows" else "/"
    try:
        usage = _psutil.disk_usage(root)
    except (PermissionError, FileNotFoundError, OSError):
        return
    pct = usage.percent
    if pct < DISK_WARN_THRESHOLD:
        _last_alert.pop("disk_warn", None)
        return
    free_gb = usage.free / (1024 ** 3)
    urgency = "high" if pct >= 98 else "normal"
    _alert("disk_warn", f"Disk {root!r} is {pct:.0f}% full ({free_gb:.1f} GB free).", urgency)


def _monitor_loop():
    logger.info("ambient_monitor: loop started")
    if _psutil is not None:
        _psutil.cpu_percent(interval=None)
    while not _stop_event.is_set():
        now = time.time()
        try:
            _check_battery()
        except Exception:
            pass
        try:
            _check_cpu(now)
        except Exception:
            pass
        try:
            _check_memory()
        except Exception:
            pass
        try:
            _check_disk()
        except Exception:
            pass
        _stop_event.wait(MONITOR_INTERVAL)
    logger.info("ambient_monitor: loop stopped")
