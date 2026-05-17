
"""Phase 0 tests — verify project structure, config keys, and entry point."""
import pytest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def test_settings_imports():
    import settings
    required_keys = [
        "LLM_MODEL", "MAX_CONTEXT_TOKENS", "ITERATION_CAPS", "VERIFICATION_MODE",
        "MAX_RAM_PERCENT", "DB_WAL_MODE", "DB_BUSY_TIMEOUT", "TOOL_RETRY_LIMITS",
        "EXECUTE_CODE_TIMEOUT", "SKILL_MATCH_THRESHOLD", "WAKE_WORD", "LOG_FILE"
    ]
    for key in required_keys:
        assert hasattr(settings, key), f"Missing settings key: {key}"

def test_required_directories_exist():
    dirs = [
        "core", "brain", "safety", "tools", "skills", "indexer", "memory",
        "verification", "perception", "output", "autonomous", "tests",
        "data", "logs", "skills/db", "indexer/db", "memory/db"
    ]
    for d in dirs:
        assert (PROJECT_ROOT / d).exists(), f"Missing directory: {d}"

def test_required_init_files():
    packages = [
        "core", "brain", "safety", "tools", "skills", "indexer",
        "memory", "verification", "perception", "output", "autonomous", "tests"
    ]
    for d in packages:
        assert (PROJECT_ROOT / d / "__init__.py").exists(), f"Missing __init__.py in {d}/"

def test_jarvis_entry_point():
    jarvis_py = PROJECT_ROOT / "jarvis.py"
    assert jarvis_py.exists()
    import importlib.util
    spec = importlib.util.spec_from_file_location("jarvis", str(jarvis_py))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "main")

def test_env_file_exists():
    assert (PROJECT_ROOT / ".env").exists() or not "Skipping — .env not required for CI"

def test_requirements_has_critical_deps():
    reqs = (PROJECT_ROOT / "requirements.txt").read_text().lower()
    critical = ["ollama", "chromadb", "pywin32", "psutil", "pillow", "pytesseract", "pytest"]
    for dep in critical:
        assert dep in reqs, f"Missing critical dependency in requirements.txt: {dep}"
