"""
Core Task Registry for JARVIS.
Provides centralized tracking of all agent tasks with real-time status updates.
"""
import uuid
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional, Dict, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class Task:
    id: str
    name: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: int = 0  # 0-100%
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "result": str(self.result) if self.result else None,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "metadata": self.metadata
        }

class TaskRegistry:
    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.RLock()
        self._listeners: List[callable] = []

    def create_task(self, name: str, description: str, metadata: Optional[Dict] = None) -> Task:
        task_id = str(uuid.uuid4())[:8]
        task = Task(
            id=task_id,
            name=name,
            description=description,
            metadata=metadata or {}
        )
        with self._lock:
            self._tasks[task_id] = task
        self._notify_listeners(task, "created")
        logger.debug(f"Task created: {task_id} - {name}")
        return task

    def update_status(self, task_id: str, status: TaskStatus, 
                      result: Any = None, error: Optional[str] = None, 
                      progress: Optional[int] = None):
        with self._lock:
            if task_id not in self._tasks:
                raise ValueError(f"Task {task_id} not found")
            
            task = self._tasks[task_id]
            old_status = task.status
            
            if status == TaskStatus.RUNNING and not task.started_at:
                task.started_at = datetime.now()
            
            if status in [TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                task.completed_at = datetime.now()
            
            task.status = status
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            if progress is not None:
                task.progress = progress

        self._notify_listeners(task, "updated")
        logger.debug(f"Task {task_id} status: {old_status.value} -> {status.value}")

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._lock:
            return self._tasks.get(task_id)

    def get_all_tasks(self, status_filter: Optional[TaskStatus] = None) -> List[Task]:
        with self._lock:
            tasks = list(self._tasks.values())
            if status_filter:
                return [t for t in tasks if t.status == status_filter]
            return tasks

    def get_active_tasks(self) -> List[Task]:
        return self.get_all_tasks(status_filter=TaskStatus.RUNNING)

    def add_listener(self, callback: callable):
        """Register a callback for task updates: callback(task, event_type)"""
        self._listeners.append(callback)

    def _notify_listeners(self, task: Task, event_type: str):
        for listener in self._listeners:
            try:
                listener(task, event_type)
            except Exception as e:
                logger.error(f"Task listener error: {e}")

    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """Remove completed tasks older than max_age_hours"""
        now = datetime.now()
        with self._lock:
            to_remove = [
                tid for tid, task in self._tasks.items()
                if task.completed_at and (now - task.completed_at).total_seconds() / 3600 > max_age_hours
            ]
            for tid in to_remove:
                del self._tasks[tid]
                logger.debug(f"Cleaned up old task: {tid}")

# Global instance
registry = TaskRegistry()
