"""
Heartbeat Monitor for JARVIS.
Continuously monitors active tasks and provides real-time status updates.
"""
import threading
import time
from typing import Callable, Optional
import logging

from core.task_registry import registry, TaskStatus

logger = logging.getLogger(__name__)

class HeartbeatMonitor:
    def __init__(self, interval: float = 2.0):
        self._interval = interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: list[Callable] = []
        self._last_status: dict[str, str] = {}

    def start(self):
        """Start the monitoring loop in background thread"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info(f"HeartbeatMonitor started (interval={self._interval}s)")

    def stop(self):
        """Stop the monitoring loop"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("HeartbeatMonitor stopped")

    def add_callback(self, callback: Callable):
        """Register a callback for status changes: callback(task_id, new_status)"""
        self._callbacks.append(callback)

    def _monitor_loop(self):
        """Main monitoring loop"""
        while self._running:
            try:
                active_tasks = registry.get_active_tasks()
                
                for task in active_tasks:
                    task_id = task.id
                    current_status = f"{task.status.value}:{task.progress}"
                    
                    # Detect status changes
                    if self._last_status.get(task_id) != current_status:
                        self._last_status[task_id] = current_status
                        self._notify_callbacks(task_id, task)
                    
                    # Check for completed tasks (shouldn't happen in active list, but safety check)
                    if task.status in [TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                        if task_id in self._last_status:
                            del self._last_status[task_id]
                
                # Clean up stale entries
                completed_ids = set(self._last_status.keys()) - {t.id for t in active_tasks}
                for tid in completed_ids:
                    del self._last_status[tid]
                
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
            
            time.sleep(self._interval)

    def _notify_callbacks(self, task_id: str, task):
        """Notify all registered callbacks of status change"""
        for callback in self._callbacks:
            try:
                callback(task_id, task)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def get_summary(self) -> str:
        """Get human-readable summary of active tasks"""
        active = registry.get_active_tasks()
        if not active:
            return "No active tasks"
        
        lines = []
        for task in active:
            elapsed = ""
            if task.started_at:
                from datetime import datetime
                delta = datetime.now() - task.started_at
                elapsed = f" [{int(delta.total_seconds())}s]"
            
            lines.append(f"• {task.name}: {task.status.value} ({task.progress}%){elapsed}")
        
        return "\n".join(lines)

# Global instance
monitor = HeartbeatMonitor(interval=2.0)
