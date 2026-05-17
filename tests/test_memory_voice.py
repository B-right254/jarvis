
"""Phase 6 tests — Memory persistence and voice I/O pipeline."""
import pytest, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory import episodic, semantic, memory_manager
from perception import stt, wake_word, input_handler
from output import tts, formatter

def test_episodic_init_and_write():
    episodic.init_db()
    episodic.write("test_session", "command", command_text="test", success=True)
    events = episodic.get_session_events("test_session")
    assert len(events) >= 1
    assert events[-1]["command_text"] == "test"

def test_semantic_set_get():
    semantic.init_db()
    semantic.upsert("test_pref", {"value": 42})
    assert semantic.fetch("test_pref") == {"value": 42}
    assert semantic.fetch("missing_key", "default") == "default"

def test_memory_manager_unified_interface():
    mm = memory_manager.MemoryManager(session_id="test_mm")
    mm.write_episodic("command", command_text="unified test", success=True)
    mm.set_preference("browser", "chrome")
    assert mm.get_preference("browser") == "chrome"
    ctx = mm.get_context_summary()
    assert isinstance(ctx, str)

def test_formatter_strips_markdown():
    raw = "**Done**. Here is `code` and ```block```."
    formatted = formatter.format_for_tts(raw)
    assert "```" not in formatted
    assert "**" not in formatted

def test_tts_mute_flag_integration(monkeypatch):
    import settings
    original_flag = settings.IS_SPEAKING.is_set()
    settings.IS_SPEAKING.clear()
    settings.TTS_ENABLED = False

    try:
        import output.tts as tts
        result = tts.speak("test", blocking=True)
        assert result is True
        assert not settings.IS_SPEAKING.is_set()
    finally:
        settings.TTS_ENABLED = True
        if original_flag:
            settings.IS_SPEAKING.set()
        else:
            settings.IS_SPEAKING.clear()

def test_input_handler_routes_correctly(monkeypatch):
    # Mock orchestrator
    class MockOrch:
        def handle(self, text): return f"Mock response to: {text}"
    mock_orch = MockOrch()
    
    # Mock TTS to avoid audio
    monkeypatch.setattr("output.tts.speak", lambda *a, **kw: True)
    
    handler = input_handler.InputHandler(mock_orch)
    # Direct route test
    handler.route("test input", source="text")
    # If no exception, routing worked

