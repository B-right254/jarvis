"""
time_calendar — time & calendar sense.

Gives Jarvis a real-time clock and the ability to read/write calendar events
via Outlook (win32com) or plain .ics files.

Actions
-------
get_time        Return current date, time, timezone, weekday, ISO week.
get_events      List upcoming calendar events (next N days).
create_event    Create a new calendar event.
delete_event    Delete/cancel an event by subject + date.

Backends
--------
outlook     Uses win32com.client — zero auth, works if Outlook is installed.
            Set CALENDAR_BACKEND=outlook in .env (default).
ics         Read/write a local .ics file.
            Set CALENDAR_BACKEND=ics and ICS_CALENDAR_PATH=/path/to/cal.ics.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import settings

logger = logging.getLogger(__name__)


def _local_tz():
    """Return the local ZoneInfo object, falling back to UTC."""
    try:
        from tzlocal import get_localzone
        return get_localzone()
    except Exception:
        pass
    try:
        import time as _time_mod
        offset = -_time_mod.timezone
        if offset == 0:
            return ZoneInfo("UTC")
        hours = offset // 3600
        return ZoneInfo(f"Etc/GMT{'+' if hours < 0 else '-'}{abs(hours)}")
    except Exception:
        return ZoneInfo("UTC")


def _now_local() -> datetime:
    return datetime.now(_local_tz())


def _outlook_get_events(days: int) -> list[dict]:
    events = []
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        cal = outlook.GetDefaultFolder(9)  # olFolderCalendar
        items = cal.Items
        items.Sort("[Start]")
        now = datetime.now()
        end = now + timedelta(days=days)
        items.IncludeRecurrences = True
        for i in range(1, min(items.Count + 1, 50)):
            try:
                item = items(i)
                start = item.Start.replace(tzinfo=None)
                if start > end:
                    break
                if start >= now:
                    events.append({
                        "subject": item.Subject,
                        "start": item.Start.isoformat(),
                        "end": item.End.isoformat(),
                        "location": item.Location,
                        "body": item.Body[:200] if item.Body else "",
                    })
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Outlook get_events failed: {e}")
    return events


def _outlook_create_event(subject, start, end, location, body, all_day):
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        appt = outlook.CreateItem(1)
        appt.Subject = subject
        appt.Start = start
        appt.End = end or (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()
        if location:
            appt.Location = location
        if body:
            appt.Body = body
        if all_day:
            appt.AllDayEvent = True
        appt.Save()
        return {"success": True, "status": f"created event '{subject}'"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _outlook_delete_event(subject, date):
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        cal = outlook.GetDefaultFolder(9)
        items = cal.Items
        items.Sort("[Start]")
        for i in range(1, items.Count + 1):
            try:
                item = items(i)
                if item.Subject == subject:
                    if date:
                        item_start = item.Start.strftime("%Y-%m-%d")
                        if item_start != date:
                            continue
                    item.Delete()
                    return {"success": True, "status": f"deleted event '{subject}'"}
            except Exception:
                continue
        return {"success": False, "error": f"event '{subject}' not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _ics_get_events(days: int) -> list[dict]:
    path = settings.ICS_CALENDAR_PATH
    if not path:
        return []
    try:
        from icalendar import Calendar
        from pathlib import Path
        cal_path = Path(path)
        if not cal_path.exists():
            return []
        with open(cal_path, encoding="utf-8") as f:
            cal = Calendar.from_ical(f.read())
        now = datetime.now()
        end = now + timedelta(days=days)
        events = []
        for comp in cal.walk():
            if comp.name == "VEVENT":
                start = comp.get("dtstart").dt
                if isinstance(start, datetime):
                    if start.tzinfo:
                        start = start.astimezone(_local_tz()).replace(tzinfo=None)
                    if now <= start <= end:
                        events.append({
                            "subject": str(comp.get("summary", "")),
                            "start": start.isoformat(),
                            "end": str(comp.get("dtend", "")),
                            "location": str(comp.get("location", "")),
                            "body": str(comp.get("description", ""))[:200],
                        })
        return events
    except Exception as e:
        logger.warning(f"ICS get_events failed: {e}")
        return []


def _ics_create_event(subject, start, end, location, body, all_day):
    path = settings.ICS_CALENDAR_PATH
    if not path:
        return {"success": False, "error": "ICS_CALENDAR_PATH not configured"}
    try:
        from icalendar import Calendar, Event
        from pathlib import Path
        cal_path = Path(path)
        if cal_path.exists():
            with open(cal_path, encoding="utf-8") as f:
                cal = Calendar.from_ical(f.read())
        else:
            cal = Calendar()
        event = Event()
        event.add("summary", subject)
        event.add("dtstart", datetime.fromisoformat(start))
        event.add("dtend", datetime.fromisoformat(end) if end else datetime.fromisoformat(start) + timedelta(hours=1))
        if location:
            event.add("location", location)
        if body:
            event.add("description", body)
        cal.add_component(event)
        with open(cal_path, "wb") as f:
            f.write(cal.to_ical())
        return {"success": True, "status": f"created event '{subject}'"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _ics_delete_event(subject, date):
    path = settings.ICS_CALENDAR_PATH
    if not path:
        return {"success": False, "error": "ICS_CALENDAR_PATH not configured"}
    try:
        from icalendar import Calendar
        from pathlib import Path
        cal_path = Path(path)
        if not cal_path.exists():
            return {"success": False, "error": "calendar file not found"}
        with open(cal_path, encoding="utf-8") as f:
            cal = Calendar.from_ical(f.read())
        new_cal = Calendar()
        deleted = False
        for comp in cal.walk():
            if comp.name == "VEVENT":
                comp_subject = str(comp.get("summary", ""))
                if comp_subject == subject:
                    if date:
                        start = comp.get("dtstart").dt
                        if isinstance(start, datetime):
                            if start.strftime("%Y-%m-%d") != date:
                                new_cal.add_component(comp)
                                continue
                    deleted = True
                    continue
            new_cal.add_component(comp)
        if not deleted:
            return {"success": False, "error": f"event '{subject}' not found"}
        with open(cal_path, "wb") as f:
            f.write(new_cal.to_ical())
        return {"success": True, "status": f"deleted event '{subject}'"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def time_calendar(
    action: str,
    subject: str = "",
    start: str = "",
    end: str = "",
    location: str = "",
    body: str = "",
    all_day: bool = False,
    days: int = 7,
    date: str = "",
    backend: str = "",
) -> dict:
    """Interact with system time and calendar."""
    try:
        backend = backend or settings.CALENDAR_BACKEND
        now = _now_local()

        if action == "get_time":
            return {
                "success": True,
                "action": "get_time",
                "datetime": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "timezone": str(now.tzinfo or _local_tz()),
                "weekday": now.strftime("%A"),
                "iso_week": now.isocalendar().week,
                "unix_timestamp": now.timestamp(),
            }

        elif action == "get_events":
            if backend == "outlook":
                events = _outlook_get_events(days)
            else:
                events = _ics_get_events(days)
            return {"success": True, "action": "get_events", "events": events, "count": len(events)}

        elif action == "create_event":
            if not subject:
                return {"success": False, "error": "subject is required"}
            if not start:
                return {"success": False, "error": "start datetime is required"}
            if not end and not all_day:
                end = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()
            if backend == "outlook":
                return _outlook_create_event(subject, start, end, location, body, all_day)
            else:
                return _ics_create_event(subject, start, end, location, body, all_day)

        elif action == "delete_event":
            if not subject:
                return {"success": False, "error": "subject is required for delete"}
            if backend == "outlook":
                return _outlook_delete_event(subject, date or now.strftime("%m/%d/%Y"))
            else:
                return _ics_delete_event(subject, date)

        else:
            return {"success": False, "error": f"Unknown action '{action}'"}

    except Exception as exc:
        logger.error(f"time_calendar error: {exc}")
        return {"success": False, "error": str(exc)}
