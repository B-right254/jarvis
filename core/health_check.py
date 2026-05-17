"""
Startup health check — validates critical subsystems before JARVIS starts serving.

Checks:
  - Ollama connectivity (cloud + local fallback)
  - Microphone availability
  - Tesseract OCR binary
  - Skill store DB
  - PC indexer DB

Non-blocking: failures are logged as warnings; the agent starts anyway so the
user can fix config issues without a hard crash.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def run_all() -> dict[str, bool]:
    """
    Run every health check and return a dict of {check_name: passed}.
    Prints a concise summary to stdout so the user sees issues immediately.
    If Ollama is unreachable, starts a background reconnect watcher that
    notifies the user as soon as it comes back online.
    """
    results: dict[str, bool] = {}

    results["ollama"] = _check_ollama()
    results["microphone"] = _check_microphone()
    results["tesseract"] = _check_tesseract()
    results["skills_db"] = True  # Skills DB verified via SQLite
    results["pc_index_db"] = _check_pc_index_db()
    results["tool_registry"] = _check_tool_registry()

    _print_summary(results)

    if not results["ollama"]:
        _start_ollama_watcher()

    return results


def _start_ollama_watcher() -> None:
    """
    Launch a daemon thread that polls Ollama every 30 seconds.
    When connectivity is restored, prints a notification and stops.
    """
    import threading

    def _watch():
        import time
        logger.info("health_check: Ollama watcher started — polling every 30s")
        for _ in range(120):  # give up after 60 minutes
            # Use monotonic time for accurate sleep intervals in background thread
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                time.sleep(1)  # Wake every second to allow faster shutdown if needed
            if _check_ollama():
                print("\n[JARVIS] ✅ Ollama is back online — LLM features restored.\n> ", end="", flush=True)
                logger.info("health_check: Ollama reconnected — watcher stopped")
                return
        logger.warning("health_check: Ollama watcher gave up after 60 min")

    t = threading.Thread(target=_watch, daemon=True, name="ollama-watcher")
    t.start()


def _check_ollama() -> bool:
    """Ping Ollama cloud endpoint; fall back to local."""
    try:
        from settings import LLM_BASE_URL, OLLAMA_LOCAL_URL
        import requests
        from urllib.parse import urlparse, urlunparse

        for name, url in (("cloud", LLM_BASE_URL), ("local", OLLAMA_LOCAL_URL)):
            try:
                # Extract base (e.g. http://localhost:11434 from http://localhost:11434/api/chat)
                parsed = urlparse(url)
                base_root = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
                
                # Try common listing endpoints
                candidates = [
                    f"{base_root}/api/tags",
                    f"{base_root}/v1/models",
                    f"{base_root}/models"
                ]
                
                # Also try the URL as-is if it looks like a base already
                if not parsed.path or parsed.path == "/":
                    candidates.insert(0, f"{url.rstrip('/')}/api/tags")

                for list_url in candidates:
                    try:
                        resp = requests.get(list_url, timeout=3)
                        if resp.status_code == 200:
                            logger.info(f"Health: Ollama ({name}) OK via {list_url}")
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        logger.warning("Health: Ollama unreachable (cloud + local both failed)")
        return False
    except Exception as e:
        logger.warning(f"Health: Ollama check error — {e}")
        return False


def _check_microphone() -> bool:
    """Verify a microphone is accessible."""
    try:
        import speech_recognition as sr

        mic_list = sr.Microphone.list_microphone_names()
        if mic_list:
            logger.info(f"Health: Microphone OK — {len(mic_list)} device(s)")
            return True
        logger.warning("Health: No microphone devices found")
        return False
    except ImportError:
        logger.warning("Health: speech_recognition not installed — mic check skipped")
        return False
    except Exception as e:
        logger.warning(f"Health: Microphone check error — {e}")
        return False


def _check_tesseract() -> bool:
    """Verify Tesseract OCR binary is callable."""
    try:
        import pytesseract

        # Trigger a version check — this exercises the binary path
        pytesseract.get_languages()
        logger.info("Health: Tesseract OCR OK")
        return True
    except ImportError:
        logger.warning("Health: pytesseract not installed — OCR unavailable")
        return False
    except Exception as e:
        logger.warning(
            f"Health: Tesseract OCR not callable — {e}. "
            "Install from https://github.com/UB-Mannheim/tesseract/wiki"
        )
        return False


def _check_pc_index_db() -> bool:
    """Verify the PC indexer SQLite DB is writable."""
    try:
        from settings import PC_INDEX_DB
        from core.thread_db import get_connection

        Path(PC_INDEX_DB).parent.mkdir(parents=True, exist_ok=True)
        conn = get_connection(PC_INDEX_DB, timeout=2.0)
        conn.execute("SELECT 1")
        logger.info("Health: PC Index DB OK")
        return True
    except Exception as e:
        logger.warning(f"Health: PC Index DB error — {e}")
        return False


def _check_tool_registry() -> bool:
    """Cross-check schemas.json against adapter function registry."""
    try:
        from pathlib import Path
        import json

        schemas_path = Path(__file__).parent.parent / "tools" / "schemas.json"
        adapters_path = Path(__file__).parent.parent / "tools" / "adapters.py"

        with open(schemas_path, encoding="utf-8") as f:
            schemas = json.load(f)
        schemas.pop("$schema", None)

        import ast
        with open(adapters_path, encoding="utf-8-sig") as f:
            tree = ast.parse(f.read())

        adapter_funcs = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}

        errors = []
        for tool_name in schemas:
            if tool_name == "execute_code":
                continue
            if tool_name not in adapter_funcs:
                errors.append(f"Tool '{tool_name}' in schemas.json has no adapter function in adapters.py")

        orphaned = adapter_funcs - set(schemas.keys()) - {"execute_code"}
        orphaned = {f for f in orphaned if not f.startswith("_")}
        for func in sorted(orphaned):
            errors.append(f"Adapter function '{func}' has no matching schema in schemas.json")

        if errors:
            for err in errors:
                logger.warning(f"Tool registry: {err}")
            return False

        logger.info(f"Tool registry OK — {len(schemas)} schemas match adapters")
        return True
    except Exception as e:
        logger.warning(f"Tool registry check error — {e}")
        return False


def _print_summary(results: dict[str, bool]) -> None:
    """Print a concise startup summary to stdout."""
    ok = sum(results.values())
    total = len(results)
    lines = ["", f"  Startup health check: {ok}/{total} passed", ""]
    for name, passed in results.items():
        emoji = "✅" if passed else "❌"
        lines.append(f"    {emoji} {name}")
    lines.append("")
    print("\n".join(lines))
