
import os
import tempfile
import sqlite3
import pytest
from pathlib import Path
import sys
import shutil

# Add jarvis directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Create temp dirs for each test run
_temp_root = tempfile.mkdtemp()
temp_skills_db = Path(_temp_root) / "skills.db"

# Save originals and override settings for testing
import settings
_orig_skills_enabled = settings.ENABLE_SKILLS
_orig_skills_db = settings.SKILLS_DB
_orig_candidate_cap = settings.SKILL_CANDIDATE_CAP
settings.ENABLE_SKILLS = True
settings.SKILLS_DB = temp_skills_db
settings.SKILL_CANDIDATE_CAP = 3

from skills.skill_store import (
    init_db, save_candidate, promote_skill, record_run,
    get_skill, search_by_intent, get_active_skills, prune_candidates
)
from skills.skill_runner import run_skill
from core.thread_db import close_thread_connections


@pytest.fixture(autouse=True)
def setup_and_teardown():
    close_thread_connections()
    if temp_skills_db.exists():
        temp_skills_db.unlink()
    init_db()
    yield
    close_thread_connections()
    if temp_skills_db.exists():
        temp_skills_db.unlink()


# Restore original settings after all tests in this file
def pytest_unconfigure():
    settings.ENABLE_SKILLS = _orig_skills_enabled
    settings.SKILLS_DB = _orig_skills_db
    settings.SKILL_CANDIDATE_CAP = _orig_candidate_cap


def test_skill_lifecycle_crud():
    # Test saving a candidate
    skill_id = save_candidate("test intent", "print('hello')", "python")
    assert skill_id != ""
    
    skill = get_skill(skill_id)
    assert skill is not None
    assert skill["status"] == "candidate"
    
    # Test promoting
    promote_skill(skill_id)
    skill = get_skill(skill_id)
    assert skill["status"] == "active"
    
    # Test recording runs
    record_run(skill_id, True)
    skill = get_skill(skill_id)
    assert skill["run_count"] == 1
    assert skill["success_count"] == 1


def test_sql_search_basic():
    # Save and promote a skill
    skill_id = save_candidate("music player", "import subprocess; subprocess.Popen('notepad.exe')")
    promote_skill(skill_id)
    
    # Search with keyword intent
    skill = search_by_intent("play some music")
    assert skill is not None
    assert skill["skill_id"] == skill_id


def test_skill_runner_executes_through_safety(monkeypatch):
    def mock_execute(*args, **kwargs):
        return {"success": True, "stdout": "test stdout", "stderr": ""}
    
    monkeypatch.setattr("skills.skill_runner.execute", mock_execute)
    
    skill_id = save_candidate("test run", "print('test')")
    promote_skill(skill_id)
    
    result = run_skill(skill_id, "test run")
    assert result["success"] is True


def test_prune_candidates_caps_memory():
    ids = []
    for i in range(settings.SKILL_CANDIDATE_CAP + 2):
        ids.append(save_candidate(f"candidate {i}", f"print({i})"))
    
    close_thread_connections()
    conn = sqlite3.connect(str(settings.SKILLS_DB))
    try:
        count_before = conn.execute("SELECT COUNT(*) FROM skills WHERE status = 'candidate'").fetchone()[0]
    finally:
        conn.close()
    assert count_before == settings.SKILL_CANDIDATE_CAP + 2
    
    prune_candidates()
    
    close_thread_connections()
    conn = sqlite3.connect(str(settings.SKILLS_DB))
    try:
        count_after = conn.execute("SELECT COUNT(*) FROM skills WHERE status = 'candidate'").fetchone()[0]
    finally:
        conn.close()
    assert count_after == settings.SKILL_CANDIDATE_CAP
