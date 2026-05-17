"""
Scans user directories via Windows Search Index (primary) or chunked os.scandir (fallback).
Pushes results to async write queue.
"""

import json
import logging
import subprocess
from pathlib import Path

from settings import INDEX_FILE_DIRS

logger = logging.getLogger(__name__)
MAX_FILES_PER_SCAN = 10000
SKIP_EXT = {".tmp", ".cache", ".log", ".pyc", ".pyo", ".db", ".sqlite"}


def _parse_mtime(mtime_val) -> float:
    """Convert PowerShell LastWriteTime to Unix timestamp float.

    PowerShell ConvertTo-Json can emit dates as:
      - /Date(epoch_ms)/  (WinForms/SOAP style)
      - ISO-8601 strings  (2024-01-15T10:30:00[.000])
      - M/D/YYYY H:MM:SS  (some locale formats)
    The DB column is REAL (Unix epoch seconds), so we normalise everything here.
    """
    if isinstance(mtime_val, (int, float)):
        return float(mtime_val)
    if isinstance(mtime_val, str):
        import re

        m = re.search(r"/Date\((\d+)\)/", mtime_val)
        if m:
            return int(m.group(1)) / 1000.0
        from datetime import datetime

        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %H:%M:%S"):
            try:
                return datetime.strptime(mtime_val, fmt).timestamp()
            except ValueError:
                continue
    return 0.0


def _windows_search_query():
    """Fallback-safe PowerShell query using INDEX_FILE_DIRS from settings."""
    # Expand and validate the configured directories
    ps_dirs = []
    for d in INDEX_FILE_DIRS:
        expanded = Path(d).expanduser()
        if expanded.exists():
            # Double-backslash so the string is safe inside a PS double-quoted string
            ps_dirs.append(str(expanded).replace("\\", "\\\\"))

    if not ps_dirs:
        return []

    dirs_ps = ", ".join(f'"{d}"' for d in ps_dirs)
    ps_cmd = f"""
$dirs = @({dirs_ps})
$results = @()
foreach ($d in $dirs) {{
    if (Test-Path $d) {{
        $results += Get-ChildItem -Path $d -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object {{ $_.Extension -notin @('.tmp','.cache','.log','.pyc','.pyo','.db','.sqlite') }} |
            Select-Object Name, FullName, Length, LastWriteTime
    }}
}}
$results | Select-Object -First {MAX_FILES_PER_SCAN} | ConvertTo-Json -Compress
"""
    try:
        proc = subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            # PowerShell ConvertTo-Json returns a dict (not list) for a single file
            if isinstance(data, dict):
                data = [data]
            return [
                {
                    "filename": i["Name"],
                    "full_path": i["FullName"],
                    "size_bytes": i["Length"],
                    "modified_at": _parse_mtime(i["LastWriteTime"]),  # fix date type
                    "directory": str(Path(i["FullName"]).parent),
                    "extension": Path(i["FullName"]).suffix.lower(),
                }
                for i in data
            ]
    except Exception:
        pass
    return []


def _fallback_scandir():
    files = []
    count = 0
    for dir_str in INDEX_FILE_DIRS:
        p = Path(dir_str).expanduser()
        if not p.exists():
            continue
        for f in p.rglob("*"):
            if count >= MAX_FILES_PER_SCAN:
                return files
            if f.is_file() and f.suffix.lower() not in SKIP_EXT:
                try:
                    stat = f.stat()
                    files.append(
                        {
                            "filename": f.name,
                            "full_path": str(f),
                            "size_bytes": stat.st_size,
                            "modified_at": stat.st_mtime,
                            "directory": str(f.parent),
                            "extension": f.suffix.lower(),
                        }
                    )
                    count += 1
                except (PermissionError, OSError):
                    continue
    return files


def scan_files(writer):
    logger.info("Running file scan...")
    files = _windows_search_query() or _fallback_scandir()
    writer.push("files", files)
    logger.info(f"File scan pushed {len(files)} records to queue")
