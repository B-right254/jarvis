"""skills.stdlib.time_cal — time and calendar helpers."""
from __future__ import annotations

from tools.comm.time_calendar import time_calendar


def get_time() -> dict:
    """Return current date, time, weekday, timezone, ISO week, unix timestamp."""
    return time_calendar(action="get_time")


def get_events(days: int = 7) -> dict:
    """Return upcoming calendar events for the next *days* days."""
    return time_calendar(action="get_events", days=days)


def create_event(
    subject: str,
    start: str,
    end: str = "",
    location: str = "",
    body: str = "",
    all_day: bool = False,
) -> dict:
    """Create a calendar event.  *start* / *end* are ISO datetime strings."""
    return time_calendar(
        action="create_event",
        subject=subject,
        start=start,
        end=end,
        location=location,
        body=body,
        all_day=all_day,
    )


def delete_event(subject: str, date: str = "") -> dict:
    """Delete a calendar event by subject (and optional date filter YYYY-MM-DD)."""
    return time_calendar(action="delete_event", subject=subject, date=date)


__all__ = ["get_time", "get_events", "create_event", "delete_event", "time_calendar"]
