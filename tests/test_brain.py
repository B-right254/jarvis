
"""Phase 4 tests — Brain, context pruning, and agent flow (mocked)."""
import pytest, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from brain.ollama_client import OllamaError
from brain.context_manager import prune_history, estimate_tokens
from brain.prompt_builder import build_system_prompt, get_pruned_schemas
from brain.response_parser import validate_tool_calls
from agents.director import JarvisAgent
from agents.execution import ExecutionAgent

def test_system_prompt_contains_rules():
    prompt = build_system_prompt()
    assert "INTENT" in prompt
    assert "Jarvis" in prompt

def test_context_manager_prunes_heavy_history():
    msgs = [{"role": "user", "content": "test"}] * 30
    pruned = prune_history(msgs, budget=50)
    assert len(pruned) < 30

def test_response_parser_validates_tools():
    valid, err = validate_tool_calls([{"function": {"name": "execute_code", "arguments": {"code": "x"}}}], {"execute_code"})
    assert valid is True

def test_response_parser_blocks_unknown():
    valid, err = validate_tool_calls([{"function": {"name": "fake_tool", "arguments": {}}}], {"execute_code"})
    assert valid is False

def test_jarvis_intent_flow(monkeypatch):
    """Jarvis outputs INTENT -> ExecutionAgent expands and executes."""
    call_count = 0

    def mock_chat(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"content": 'INTENT {"action":"get_info","target":"system"}', "tool_calls": None, "model": "test", "done": True}
        return {"content": "Here's the system info.", "tool_calls": None, "model": "test", "done": True}

    monkeypatch.setattr("brain.ollama_client.chat", mock_chat)

    executed = []
    def mock_exec(name, args):
        executed.append(name)
        return {"success": True, "output": f"ran {name}", "data": {}}
    def mock_verify(name, res, exp):
        return {"status": "CONFIRMED"}
    exec_agent = ExecutionAgent(mock_exec, mock_verify)
    jarvis = JarvisAgent()

    result = jarvis.process("check system status", [], intent_handler=exec_agent.execute_intent)
    assert call_count >= 1
    assert result["success"] is True
