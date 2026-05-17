"""
Immutable pre/post execution log. JSON lines format with rolling hash chain.
Each entry includes the SHA-256 hash of the previous entry, making
tampering detectable.
"""

import hashlib
import json
import logging
import threading
import time

from settings import LOGS_DIR

logger = logging.getLogger(__name__)
_log_file = LOGS_DIR / "audit.log"
_MAX_BYTES = 10 * 1024 * 1024  # rotate at 10 MB
_write_lock = threading.Lock()  # serialize concurrent writes from scheduler/main threads
_prev_hash = None  # rolling hash of the last written entry


def setup():
    _log_file.parent.mkdir(parents=True, exist_ok=True)
    # Recover the previous hash by reading the last line
    global _prev_hash
    try:
        if _log_file.exists() and _log_file.stat().st_size > 0:
            with open(_log_file, "r", encoding="utf-8") as f:
                last_line = None
                for last_line in f:
                    pass
                if last_line:
                    last_entry = json.loads(last_line)
                    _prev_hash = last_entry.get("hash", "")
    except Exception:
        _prev_hash = None
    logger.info(f"Audit log initialized: {_log_file}")


def _rotate():
    """Rotate audit log with numbered backups (max 5)."""
    _log_file.parent.mkdir(parents=True, exist_ok=True)
    # Shift existing backups: .log.5 -> remove, .log.4 -> .log.5, etc.
    for i in range(4, 0, -1):
        src = _log_file.with_suffix(f".log.{i}")
        dst = _log_file.with_suffix(f".log.{i + 1}")
        if src.exists():
            src.rename(dst)
    # Rename current log to .log.1
    _log_file.rename(_log_file.with_suffix(".log.1"))


def _write(entry: dict) -> None:
    """Append one JSON-lines entry, rotating the file at 10 MB (numbered backups)."""
    global _prev_hash
    try:
        with _write_lock:
            # Add rolling hash chain
            entry["prev_hash"] = _prev_hash or ""
            entry_str = json.dumps(entry, default=str, sort_keys=True)
            entry_hash = hashlib.sha256(entry_str.encode()).hexdigest()[:16]
            entry["hash"] = entry_hash
            _prev_hash = entry_hash

            if _log_file.exists() and _log_file.stat().st_size >= _MAX_BYTES:
                _rotate()
            with open(_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str, sort_keys=True) + "\n")
    except Exception as exc:
        # Never let an audit-log failure propagate to the tool caller
        logger.error(f"audit_log write failed: {exc}")


def log_call(tool_name: str, args: dict, result) -> None:
    success = False
    error = None
    returncode = None
    if isinstance(result, dict):
        success = result.get("success", False)
        error = result.get("error")
        returncode = result.get("returncode")
    elif isinstance(result, list):
        success = True
    _write(
        {
            "ts": time.time(),
            "tool": tool_name,
            "args": args,
            "success": success,
            "error": error,
            "returncode": returncode,
        }
    )


def log_blocked(tool_name: str, args: dict, reason: str) -> None:
    _write(
        {
            "ts": time.time(),
            "tool": tool_name,
            "args": args,
            "blocked": True,
            "reason": reason,
        }
    )
