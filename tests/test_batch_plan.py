"""Tests for INTENT flow: Jarvis agent + Execution agent expansion."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.director import JarvisAgent
from agents.execution import ExecutionAgent, EXPANDERS


# ── INTENT parsing tests ─────────────────────────────────────────────────────

def test_parse_intent_valid():
    agent = JarvisAgent()
    intent = agent._parse_intent('INTENT {"action":"open","target":"chrome"}')
    assert intent is not None
    assert intent["action"] == "open"
    assert intent["target"] == "chrome"


def test_parse_intent_no_prefix():
    agent = JarvisAgent()
    assert agent._parse_intent("Hello, how can I help?") is None


def test_parse_intent_invalid_json():
    agent = JarvisAgent()
    assert agent._parse_intent("INTENT {bad json}") is None


def test_parse_intent_empty():
    agent = JarvisAgent()
    assert agent._parse_intent("") is None


def test_parse_intent_extra_whitespace():
    agent = JarvisAgent()
    intent = agent._parse_intent('  INTENT  {"action":"close"}  ')
    assert intent is not None
    assert intent["action"] == "close"


def test_parse_intent_trailing_text():
    """LLM sometimes adds commentary after INTENT — raw_decode handles it."""
    agent = JarvisAgent()
    intent = agent._parse_intent('INTENT {"action":"open","target":"notepad"}\n(Note: awaiting execution result...)')
    assert intent is not None
    assert intent["action"] == "open"
    assert intent["target"] == "notepad"


def test_parse_intent_trailing_text_no_newline():
    """No newline between INTENT and trailing text."""
    agent = JarvisAgent()
    intent = agent._parse_intent('INTENT {"action":"click","x":100}(doing it now)')
    assert intent is not None
    assert intent["action"] == "click"


# ── Execution agent expander tests ───────────────────────────────────────────

def test_expander_open():
    expander = EXPANDERS.get("open")
    assert expander is not None
    steps = expander({"action": "open", "target": "notepad"})
    assert len(steps) == 3
    assert steps[0]["tool"] == "get_active_window"
    assert callable(steps[1])
    assert steps[2]["tool"] == "get_active_window"


def test_expander_open_callable_resolves():
    """Verify callable steps accept prior_results argument (matching _run_step)."""
    expander = EXPANDERS.get("open")
    steps = expander({"action": "open", "target": "notepad"})
    # Simulate _run_step: callable(prior_results) -> resolved dict
    prior = [{"tool": "get_active_window", "success": True, "result": {"data": {"window_title": "SomeApp"}}}]
    resolved = steps[1](prior)
    assert isinstance(resolved, dict)
    assert "tool" in resolved
    # Target not active, so should return open_app
    assert resolved["tool"] == "open_app"


def test_expander_open_already_active():
    """When target is already active, callable returns get_active_window."""
    expander = EXPANDERS.get("open")
    steps = expander({"action": "open", "target": "someapp"})
    prior = [{"tool": "get_active_window", "success": True, "result": {"data": {"window_title": "SomeApp Window"}}}]
    resolved = steps[1](prior)
    assert resolved["tool"] == "get_active_window"


def test_expander_close_with_target():
    expander = EXPANDERS.get("close")
    steps = expander({"action": "close", "target": "chrome"})
    assert len(steps) == 1
    assert steps[0]["tool"] == "close_app"
    assert steps[0]["params"]["name"] == "chrome"


def test_expander_close_no_target():
    expander = EXPANDERS.get("close")
    steps = expander({"action": "close"})
    assert len(steps) == 2
    assert callable(steps[0]) or steps[0]["tool"] == "get_active_window"
    assert callable(steps[1])


def test_expander_search():
    expander = EXPANDERS.get("search")
    steps = expander({"action": "search", "query": "cat videos"})
    assert len(steps) == 3
    assert steps[0]["tool"] == "open_app"
    assert "cat" in steps[1]["params"]["text"]


def test_expander_search_custom_engine():
    expander = EXPANDERS.get("search")
    steps = expander({"action": "search", "query": "music", "engine": "youtube"})
    assert "youtube" in steps[1]["params"]["text"]


def test_expander_click_coordinates():
    expander = EXPANDERS.get("click")
    steps = expander({"action": "click", "x": 100, "y": 200})
    assert len(steps) == 3
    # Step 1 should be the click
    click_step = steps[1]
    assert click_step["tool"] == "click"
    assert click_step["params"]["x"] == 100
    assert click_step["params"]["y"] == 200


def test_expander_click_text_target():
    expander = EXPANDERS.get("click")
    steps = expander({"action": "click", "target": "Submit"})
    assert len(steps) == 3
    assert steps[0]["tool"] == "detect_ui_elements"
    assert steps[0]["params"]["text"] == "Submit"
    assert callable(steps[1])  # resolve click from detection result


def test_expander_type():
    expander = EXPANDERS.get("type")
    steps = expander({"action": "type", "text": "hello world"})
    assert len(steps) == 2
    assert steps[1]["tool"] == "type_text"
    assert steps[1]["params"]["text"] == "hello world"


def test_expander_scroll():
    expander = EXPANDERS.get("scroll")
    steps = expander({"action": "scroll", "direction": "down", "amount": 5})
    assert len(steps) == 2
    assert steps[1]["tool"] == "scroll"
    assert steps[1]["params"]["clicks"] == 5  # positive = down


def test_expander_scroll_up():
    expander = EXPANDERS.get("scroll")
    steps = expander({"action": "scroll", "direction": "up", "amount": 3})
    assert steps[1]["params"]["clicks"] == -3  # negative = up


def test_expander_scroll_default():
    expander = EXPANDERS.get("scroll")
    steps = expander({"action": "scroll"})
    assert steps[1]["params"]["clicks"] == 3  # default amount=3, direction=down = positive


def test_expander_screenshot():
    expander = EXPANDERS.get("screenshot")
    steps = expander({"action": "screenshot"})
    assert len(steps) == 1
    assert steps[0]["tool"] == "screenshot"


def test_expander_read_screen():
    expander = EXPANDERS.get("read_screen")
    steps = expander({"action": "read_screen"})
    assert len(steps) == 1
    assert steps[0]["tool"] == "read_screen"


def test_expander_get_info():
    expander = EXPANDERS.get("get_info")
    steps = expander({"action": "get_info", "target": "battery"})
    assert steps[0]["tool"] == "get_battery"


def test_expander_get_info_system():
    expander = EXPANDERS.get("get_info")
    steps = expander({"action": "get_info", "target": "system"})
    assert steps[0]["tool"] == "get_system_stats"


def test_expander_get_info_time():
    expander = EXPANDERS.get("get_info")
    steps = expander({"action": "get_info", "target": "time"})
    assert steps[0]["tool"] == "time_calendar"
    assert steps[0]["params"]["action"] == "get_time"


def test_expander_unknown_action():
    assert "nonexistent" not in EXPANDERS


def test_all_actions_registered():
    expected = {"open", "close", "search", "click", "type", "scroll",
                "screenshot", "read_screen", "wait", "shutdown", "restart",
                "get_info", "press_keys", "move_mouse", "list_apps",
                "open_url", "manage_window"}
    assert set(EXPANDERS.keys()) == expected


# ── Execution agent execution tests ──────────────────────────────────────────

def _mock_exec(tool_name, args):
    return {"success": True, "output": f"ran {tool_name}", "data": {}}


def _mock_verify(tool_name, result, expected):
    return {"status": "CONFIRMED"}


def test_execute_unknown_action():
    agent = ExecutionAgent(_mock_exec, _mock_verify)
    result = agent.execute_intent({"action": "bogus"})
    assert "Unknown action" in result


def test_execute_type():
    agent = ExecutionAgent(_mock_exec, _mock_verify)
    result = agent.execute_intent({"action": "type", "text": "hello"})
    assert "type_text" in result
    assert "ok" in result


# ── New expander tests ───────────────────────────────────────────────────────

def test_expander_press_keys():
    expander = EXPANDERS.get("press_keys")
    steps = expander({"action": "press_keys", "keys": "ctrl+c"})
    assert len(steps) == 2
    assert steps[0]["tool"] == "get_active_window"
    assert steps[1]["tool"] == "press_keys"
    assert steps[1]["params"]["keys"] == "ctrl+c"


def test_expander_move_mouse():
    expander = EXPANDERS.get("move_mouse")
    steps = expander({"action": "move_mouse", "x": 500, "y": 300})
    assert len(steps) == 2
    assert steps[1]["tool"] == "move_mouse"
    assert steps[1]["params"]["x"] == 500
    assert steps[1]["params"]["y"] == 300


def test_expander_list_apps_installed():
    expander = EXPANDERS.get("list_apps")
    steps = expander({"action": "list_apps"})
    assert steps[0]["tool"] == "list_installed_apps"


def test_expander_list_apps_running():
    expander = EXPANDERS.get("list_apps")
    steps = expander({"action": "list_apps", "target": "running"})
    assert steps[0]["tool"] == "list_running_apps"


def test_expander_open_url():
    expander = EXPANDERS.get("open_url")
    steps = expander({"action": "open_url", "url": "https://example.com"})
    assert len(steps) == 2
    assert steps[0]["tool"] == "open_app"
    assert steps[0]["params"]["name"] == "browser"
    assert steps[1]["tool"] == "open_url"
    assert steps[1]["params"]["url"] == "https://example.com"


def test_expander_manage_window_focus():
    expander = EXPANDERS.get("manage_window")
    steps = expander({"action": "manage_window", "action": "focus", "target": "chrome"})
    assert len(steps) == 2
    assert steps[1]["tool"] == "focus_window"
    assert steps[1]["params"]["name"] == "chrome"


def test_expander_manage_window_minimize():
    expander = EXPANDERS.get("manage_window")
    steps = expander({"action": "manage_window", "target": "notepad"})
    assert steps[1]["tool"] == "focus_window"  # default action is focus


def test_expander_manage_window_close():
    expander = EXPANDERS.get("manage_window")
    steps = expander({"action": "manage_window", "action": "close", "target": "calc"})
    assert steps[1]["tool"] == "close_app"
    assert steps[1]["params"]["name"] == "calc"


# ── Edge case tests ──────────────────────────────────────────────────────────

def test_expander_open_missing_target():
    expander = EXPANDERS.get("open")
    steps = expander({"action": "open"})
    # Should still produce 3 steps even without target
    assert len(steps) == 3
    assert steps[0]["tool"] == "get_active_window"
    assert callable(steps[1])  # check_and_act (will return get_active_window with empty target)
    assert steps[2]["tool"] == "get_active_window"


def test_expander_search_missing_query():
    expander = EXPANDERS.get("search")
    steps = expander({"action": "search"})
    assert len(steps) == 3
    assert steps[1]["tool"] == "type_text"


def test_expander_type_missing_text():
    expander = EXPANDERS.get("type")
    steps = expander({"action": "type"})
    assert steps[1]["params"]["text"] == ""


def test_expander_get_info_case_insensitive():
    expander = EXPANDERS.get("get_info")
    steps = expander({"action": "get_info", "target": "SYSTEM"})
    assert steps[0]["tool"] == "get_system_stats"


def test_expander_get_info_unknown_target():
    expander = EXPANDERS.get("get_info")
    steps = expander({"action": "get_info", "target": "network"})
    assert steps[0]["tool"] == "get_system_stats"  # falls back to default


def test_execute_expander_failure(monkeypatch):
    """Execution agent aborts after failed step."""
    def _bad_exec(tool_name, args):
        return {"success": False, "error": "mock fail"}
    agent = ExecutionAgent(_bad_exec, _mock_verify)
    result = agent.execute_intent({"action": "type", "text": "hello"})
    assert "mock fail" in result
    assert "0/1" in result  # aborted after 1st step (get_active_window)


def test_execute_abort_on_fail():
    """Failed step aborts remaining steps."""
    call_log = []
    def _exec(name, args):
        call_log.append(name)
        success = name != "click"
        return {"success": success, "error": "" if success else "fail"}
    agent = ExecutionAgent(_exec, _mock_verify)
    result = agent.execute_intent({"action": "click", "x": 100, "y": 200})
    # Should abort after click failure, so get_active_window (verify) is skipped
    assert call_log.count("click") == 1
    # get_active_window appears twice (before+after click) - only 1st runs
    assert "partial" in result or "failed" in result
