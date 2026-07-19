from datetime import datetime, timedelta

from .. import config, gapi

CAL = "https://www.googleapis.com/calendar/v3/calendars/primary"


async def list_events(time_min=None, time_max=None, max_results=15):
    now = datetime.now(config.TZ)
    params = {
        "timeMin": time_min or now.isoformat(),
        "timeMax": time_max or (now + timedelta(days=1)).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": max_results,
    }
    data = await gapi.api("GET", f"{CAL}/events", params=params)
    out = []
    for ev in data.get("items", []) or []:
        start = ev.get("start", {})
        out.append(
            {
                "title": ev.get("summary", "(ללא כותרת)"),
                "start": start.get("dateTime") or start.get("date"),
                "end": ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date"),
                "all_day": "date" in start,
            }
        )
    return out


async def create_event(title, start_iso, end_iso=None, reminder_minutes=None, description=None):
    start = datetime.fromisoformat(start_iso)
    if start.tzinfo is None:
        start = start.replace(tzinfo=config.TZ)
    end = datetime.fromisoformat(end_iso) if end_iso else start + timedelta(hours=1)
    if end.tzinfo is None:
        end = end.replace(tzinfo=config.TZ)
    body = {
        "summary": title,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }
    if description:
        body["description"] = description
    if reminder_minutes:
        body["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": int(m)} for m in reminder_minutes],
        }
    await gapi.api("POST", f"{CAL}/events", json=body)
    return {
        "confirm_to_user": f"📅 נוצר ביומן: {title} — {start:%Y-%m-%d %H:%M}"
                           + (f" (תזכורות: {reminder_minutes} דק' לפני)" if reminder_minutes else "")
    }


async def busy_now() -> bool:
    now = datetime.now(config.TZ)
    events = await list_events(now.isoformat(), (now + timedelta(minutes=1)).isoformat(), 5)
    return any(not ev["all_day"] for ev in events)


def build(ctx):
    async def _list(time_min=None, time_max=None):
        return {"events": await list_events(time_min, time_max)}

    async def _create(title, start_iso, end_iso=None, reminder_minutes=None, description=None):
        return await create_event(title, start_iso, end_iso, reminder_minutes, description)

    return {
        "list_events": (
            {
                "type": "function",
                "function": {
                    "name": "list_events",
                    "description": (
                        "List Google Calendar events. Defaults to the next 24h. "
                        "Pass ISO datetimes to change the window (e.g. tomorrow, next week)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "time_min": {"type": "string", "description": "ISO start of window"},
                            "time_max": {"type": "string", "description": "ISO end of window"},
                        },
                    },
                },
            },
            _list,
        ),
        "create_event": (
            {
                "type": "function",
                "function": {
                    "name": "create_event",
                    "description": (
                        "Create a Google Calendar event. reminder_minutes is a list of "
                        "minutes-before for popup reminders (e.g. [40, 1440] = 40 min "
                        "and one day before)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "start_iso": {"type": "string"},
                            "end_iso": {"type": "string"},
                            "reminder_minutes": {"type": "array", "items": {"type": "integer"}},
                            "description": {"type": "string"},
                        },
                        "required": ["title", "start_iso"],
                    },
                },
            },
            _create,
        ),
    }
