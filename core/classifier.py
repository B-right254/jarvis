"""
Fast-path intent classifier — routes common queries directly to tools
without an LLM call. Pure analysis, no side effects.

Returns a Classification namedtuple or None if no match.
"""

import re
from dataclasses import dataclass
from typing import Callable


@dataclass
class Classification:
    tool_name: str
    args: dict
    format_result: Callable[[dict], str]
    label: str = ""


def _fmt_battery(result: dict) -> str:
    data = result.get("data", result)
    pct = data.get("battery_percent")
    plugged = data.get("plugged_in")
    if pct is None:
        return "No battery detected (desktop or VM)."
    status = "plugged in" if plugged else "on battery"
    return f"Battery: {pct}% ({status})"


def _fmt_time(result: dict) -> str:
    data = result.get("data", result)
    t = data.get("time")
    tz = data.get("timezone", "")
    return f"{t} {tz}".strip() if t else str(data.get("datetime", ""))


def _fmt_date(result: dict) -> str:
    data = result.get("data", result)
    d = data.get("date")
    w = data.get("weekday", "")
    return f"{d} ({w})".strip() if d else str(data.get("datetime", ""))


def _fmt_system_stats(result: dict) -> str:
    data = result.get("data", result)
    parts = []
    if "cpu_percent" in data:
        parts.append(f"CPU: {data['cpu_percent']}%")
    if "ram_percent" in data:
        parts.append(f"RAM: {data['ram_percent']}% ({data.get('ram_free_gb', '?')} GB free)")
    if "disk_percent" in data:
        parts.append(f"Disk: {data['disk_percent']}% ({data.get('disk_free_gb', '?')} GB free)")
    bp = data.get("battery_percent")
    if bp is not None:
        parts.append(f"Battery: {bp}%")
    return " | ".join(parts) if parts else str(data.get("status", "System stats unavailable"))


def _fmt_plain(result: dict) -> str:
    return str(result.get("status") or result.get("message") or "Done.")


_SIMPLE_INTENTS: list[tuple[str, str, dict, Callable]] = [
    (r"^(battery|charge)( |$)", "get_battery", {}, _fmt_battery),
    (r"\b(battery|charge)\b.*(percent|level|remaining|plug|status|\d+)", "get_battery", {}, _fmt_battery),
    (r"^(what('?s| is)? (my )?(battery|charge) )|^(check|show|tell me) (my )?(battery|charge)", "get_battery", {}, _fmt_battery),
    (r"\bwhat.*time\b|\btime\b$|\bcurrent time\b|\bclock\b", "time_calendar", {"action": "get_time"}, _fmt_time),
    (r"\bwhat.*date\b|\btoday'?s date\b|\bcurrent date\b|\bdate\b$", "time_calendar", {"action": "get_time"}, _fmt_date),
    (r"^(cpu|ram|memory|disk|system stats|system status)", "get_system_stats", {}, _fmt_system_stats),
    (r"\bhow much ram\b|\bram usage\b|\bmemory usage\b|\bfree memory\b", "get_system_stats", {}, _fmt_system_stats),
    (r"\bcpu usage\b|\bcpu percent\b", "get_system_stats", {}, _fmt_system_stats),
    (r"\bdisk (usage|space|free)\b|\bfree space\b", "get_system_stats", {}, _fmt_system_stats),
]




def classify(text: str) -> Classification | None:
    text_lower = text.strip().lower()

    for pattern, tool_name, fixed_args, fmt in _SIMPLE_INTENTS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return Classification(
                tool_name=tool_name,
                args=fixed_args,
                format_result=fmt,
                label=f"simple:{tool_name}",
            )

    return None


def is_special_command(text: str) -> str | None:
    """Check for admin/debug commands. Returns the command name or None."""
    t = text.strip().lower()
    if t == "skills status":
        return "skills_status"
    if t == "summary":
        return "summary"
    if t == "status":
        return "status"
    if t.startswith("task status"):
        return "task_status"
    return None
