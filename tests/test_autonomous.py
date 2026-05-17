
"""Phase 7 tests — Autonomous operation: queue, approval, scheduler, logging."""
import pytest, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from autonomous import task_queue, approval_gate, scheduler, activity_log

def test_task_queue_crud():
    task_queue.init_db()
    tid = task_queue.create_task("test command", confidence_required=0.9)
    assert tid is not None
    
    pending = task_queue.get_pending_tasks()
    assert any(t["task_id"] == tid for t in pending)
    
    task_queue.update_task(tid, "running")
    task = task_queue.get_task(tid)
    assert task["status"] == "running"
    
    task_queue.update_task(tid, "complete", result={"response": "done"})
    task = task_queue.get_task(tid)
    assert task["status"] == "complete"
    assert task["result"]["response"] == "done"

def test_approval_gate_flow():
    gate = approval_gate.ApprovalGate(timeout_seconds=1)
    tid = "test-approval-123"
    # request() is blocking — with timeout=1 it will return False (denied on timeout)
    # We can't easily test interactive approval in a non-interactive test,
    # so we verify the gate instantiates and its timeout behaviour.
    import threading
    result = [None]
    def _try_request():
        result[0] = gate.request(tid, "test cmd", 0.88)
    t = threading.Thread(target=_try_request, daemon=True)
    t.start()
    t.join(timeout=3)
    assert result[0] is False  # Timed out → denied

def test_scheduler_cron_parsing():
    sched = scheduler.Scheduler(lambda cmd: "mock")
    now = time.time()
    
    # "every 5 minutes"
    ts = sched._parse_cron("every 5 minutes")
    assert ts is not None and ts > now and ts <= now + 300
    
    # "every day at 09:00"
    ts = sched._parse_cron("every day at 09:00")
    assert ts is not None
    
    # Invalid expression
    assert sched._parse_cron("invalid cron") is None

def test_activity_log_summary():
    task_queue.init_db()
    tid = task_queue.create_task("autonomous test", confidence_required=0.85)
    task_queue.update_task(tid, "running")
    task_queue.update_task(tid, "complete", result={"response": "completed successfully"})
    
    summary = activity_log.generate_summary(task_id=tid)
    assert "autonomous test" in summary
    assert "complete" in summary.lower()

def test_pending_approvals_filter():
    task_queue.init_db()
    # Create a high-confidence pending task
    tid = task_queue.create_task("high-conf task", confidence_required=0.95)
    
    pending = activity_log.get_pending_approvals()
    assert any(t["task_id"] == tid for t in pending)
    
    # Low-confidence task should not appear
    tid2 = task_queue.create_task("low-conf task", confidence_required=0.6)
    pending = activity_log.get_pending_approvals()
    assert not any(t["task_id"] == tid2 for t in pending)

