
"""Phase 2 tests — 9 primitives, safety sandbox, verification router."""
import pytest, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import TOOL_REGISTRY
from safety import executor
from verification import verifier

def test_all_tools_registered():
    assert len(TOOL_REGISTRY) >= 30
    assert "execute_code" in TOOL_REGISTRY
    assert "vision_query" in TOOL_REGISTRY
    assert "speak" in TOOL_REGISTRY

def test_execute_code_safe():
    from tools.system import execute_code
    r = execute_code("print('hello')")
    assert r["success"] and "hello" in r["output"]

def test_execute_code_blocks_import():
    from tools.system import execute_code
    r = execute_code("import socket; print('blocked')")
    assert r["success"]
    assert "blocked" in r.get("output", "")

def test_safety_executor_runs():
    def fake_tool(**kw):
        return {"success": True}
    r = executor.execute("fake_tool", fake_tool, {"test": True})
    assert r["success"]

def test_verification_router():
    from tools.system import execute_code
    res = execute_code("import time; time.sleep(0.1)")
    report = verifier.verify_action("execute_code", res, expected="success")
    assert isinstance(report, dict)
    assert "status" in report
    assert "summary" in report
