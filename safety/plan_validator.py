"""
Plan validator — scans code/commands for destructive patterns before execution.
Blocks anything that could cause irreversible system damage.
"""

import logging
import re

logger = logging.getLogger(__name__)

# (pattern, human-readable reason) — checked against the code/command string
_DANGEROUS: list[tuple[str, str]] = [
    # Shell command patterns (direct execution)
    (r"\brm\s+-[rRfF]{1,3}\b", "Destructive recursive delete (rm -rf)"),
    # Python subprocess with rm -rf in list form (e.g. ["rm", "-rf", ...])
    (r"subprocess.*?['\"]rm['\"].*?['\"]-[rRfF]+", "Destructive recursive delete via subprocess (rm -rf list)"),
    # Python subprocess with rm -rf in shell-string form (e.g. "rm -rf /")
    (r"subprocess\.(?:run|Popen|call)\(.*?['\"]rm\s+-[rRfF]+", "Destructive recursive delete via subprocess (rm -rf shell string)"),
    # Python os.system / os.popen — blanket block (all forms are dangerous)
    (r"os\.(?:system|popen)\s*\(", "Shell execution via os.system/popen (all forms blocked)"),
    (r"os\.(?:system|popen)\(.*?rm\s+-[rRfF]+", "Destructive recursive delete via os.system/popen (rm -rf)"),
    (r"\bdel\s+/[sStTfFqQ]", "Destructive del command"),
    (r"\brd\s+/[sS]", "Recursive directory removal (rd /s)"),
    (r"\bformat\s+[a-zA-Z]:", "Disk format command"),
    (r"\bshutdown\s*/[rsRShH]", "System shutdown or restart"),
    (r"\breg\s+delete\b", "Windows registry deletion"),
    (r"\bdiskpart\b", "Disk partition tool (diskpart)"),
    (r"\bbcdedit\b", "Boot configuration edit (bcdedit)"),
    (r"\bcipher\s+/[wW]", "Secure wipe (cipher /w)"),
    (r"\bsfc\s*/scannow\b", "System file checker (requires elevation)"),
    # Only block shutil.rmtree (recursive), NOT os.rmdir (single empty dir)
    (r"shutil\.rmtree", "Recursive directory removal (shutil.rmtree)"),
    # Python registry deletion
    (r"winreg\.DeleteKey", "Windows registry deletion (winreg.DeleteKey)"),
    (r"winreg\.DeleteValue", "Windows registry value deletion (winreg.DeleteValue)"),
    # PowerShell destructive commands
    (r"\bRemove-Item\b.*-Recurse\b", "PowerShell recursive delete (Remove-Item -Recurse)"),
    (r"\bFormat-Volume\b", "PowerShell format volume (Format-Volume)"),
    (r"\bStop-Computer\b", "PowerShell shutdown (Stop-Computer)"),
    (r"\bRestart-Computer\b", "PowerShell restart (Restart-Computer)"),
    (r"\bRemove-ItemProperty\b", "PowerShell registry deletion (Remove-ItemProperty)"),
    (
        r"(?:subprocess\.(?:run|Popen|call)|os\.(?:system|popen)).*?(\bformat\b|\brd\s+/s\b|\bshutdown\b)",
        "Calling destructive command via subprocess or os.system",
    ),
    # Dangerous dynamic code execution
    (r"\beval\s*\(", "Dynamic code execution (eval)"),
    (r"\bexec\s*\(", "Dynamic code execution (exec)"),
    (r"\b__import__\s*\(", "Dynamic import (potential bypass)"),
    (r"\bcompile\s*\(", "Dynamic code compilation (compile)"),
]

# ── Temp-directory allow-list ─────────────────────────────────────────────────
# When a script uses shutil.rmtree / os.rmdir but the code also contains clear
# evidence it is operating on a temp / cache directory, we allow it.
# This lets JARVIS perform legitimate cleanup tasks (clear temp files, empty
# recycle bin, purge cache) without triggering a false-positive block.
_TEMP_CONTEXT = re.compile(
    # Standard library / API names
    r"tempfile"
    r"|gettempdir"
    # Environment variables (any case)
    r"|%TEMP%"
    r"|%TMP%"
    r"|LOCALAPPDATA"
    # File extensions / path fragments
    r"|\.tmp\b"
    r"|[/\\\\]Temp[/\\\\'\"\.]"
    r"|\/tmp\/"
    r"|AppData.{0,40}Temp"
    r"|Windows.{0,10}Temp"
    r"|os\.environ.*TEMP"
    # Variable-name prefix: temp_dir, temp_path, tmp_folder, temporary, etc.
    # No trailing \b so it matches temp_ prefixed names and 'temporary'.
    r"|\btemp"
    r"|\btmp"
    # Semantic indicators
    r"|recycle"
    r"|cleanmgr"
    r"|\bcache\b"
    r"|\bjunk\b"
    r"|\bcleanup\b",
    re.IGNORECASE,
)

# Patterns in _DANGEROUS whose block can be lifted when temp context is present.
_TEMP_LIFTABLE = frozenset(
    {
        "Recursive directory removal (shutil.rmtree)",
        "PowerShell recursive delete (Remove-Item -Recurse)",
    }
)


def validate(plan: dict) -> tuple[bool, str]:
    """
    Scan a plan dict for dangerous patterns.

    Checks:
      - plan["code"]    (execute_code scripts)
      - plan["command"] (shell commands)
      - plan["args"]    (arbitrary tool arguments as string)

    Returns (True, "") if safe, (False, reason) if blocked.
    """
    if not plan:
        return True, ""

    # Gather all text surfaces to scan
    surfaces: list[str] = []
    for key in ("code", "command", "args"):
        val = plan.get(key)
        if isinstance(val, str):
            surfaces.append(val)
        elif isinstance(val, dict):
            surfaces.append(str(val))

    combined = "\n".join(surfaces)
    if not combined.strip():
        return True, ""

    for pattern, reason in _DANGEROUS:
        if not re.search(pattern, combined, re.IGNORECASE):
            continue

        # ── Temp-context exemption ──────────────────────────────────────
        # shutil.rmtree / os.rmdir are blocked by default, but we lift the
        # block when the code is clearly operating on a temp or cache dir
        # (e.g. clearing %TEMP%, purging a .tmp folder, emptying a cache).
        if reason in _TEMP_LIFTABLE and _TEMP_CONTEXT.search(combined):
            logger.debug(
                "plan_validator: lifting '%s' block — temp/cache context detected",
                reason,
            )
            continue

        logger.warning(f"plan_validator: BLOCKED — {reason}")
        return False, f"Blocked: {reason}"

    return True, ""
