"""Phase 5 tests — Orchestrator wiring."""
import pytest, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.orchestrator import Orchestrator

def test_orchestrator_instantiates_clean():
    orc = Orchestrator()
    assert len(orc._history) == 0
    assert orc._mode == "interactive_cloud"
    assert orc.running is True

def test_mode_switching_valid():
    orc = Orchestrator()
    orc.set_mode("interactive_local")
    assert orc._mode == "interactive_local"
