"""Morning brief — fully code-formatted, the model never words it."""

from datetime import datetime, timedelta

from .. import config
from . import gcal, gmail_skill


async def build_brief(engine) -> str:
    now = datetime.now(config.TZ)
    end_of_day = now.replace(hour=23, minute=59, second=0)
    lines = [f"☀️ בוקר טוב — {now:%A %d.%m}"]

    events = await gcal.list_events(now.isoformat(), end_of_day.isoformat())
    lines.append("\n📅 היום:")
    if events:
        for ev in events:
            if ev["all_day"]:
                lines.append(f"• (כל היום) {ev['title']}")
            else:
                start = datetime.fromisoformat(ev["start"]).astimezone(config.TZ)
                lines.append(f"• {start:%H:%M} {ev['title']}")
    else:
        lines.append("• אין אירועים 🎉")

    todays = []
    for row in engine.list_checkins():
        if row["repeat"] == "daily":
            todays.append(f"• {'⏰' if row['kind'] == 'alarm' else '❓'} {row['at_time']} {row['question']}")
        elif row["at_iso"] and datetime.fromisoformat(row["at_iso"]).date() == now.date():
            when = datetime.fromisoformat(row["at_iso"])
            todays.append(f"• {'⏰' if row['kind'] == 'alarm' else '❓'} {when:%H:%M} {row['question']}")
    if todays:
        lines.append("\n⏰ קבוע להיום:")
        lines.extend(todays)

    emails = await gmail_skill.search_emails("is:unread newer_than:1d in:inbox", 5)
    if emails:
        lines.append(f"\n📧 לא נקראו ({len(emails)}):")
        for em in emails:
            sender = em["from"].split("<")[0].strip().strip('"')[:30]
            lines.append(f"• {sender}: {em['subject'][:60]}")

    return "\n".join(lines)


def build(ctx):
    engine = ctx["engine"]

    async def _brief():
        return {"confirm_to_user": await build_brief(engine)}

    return {
        "morning_brief": (
            {
                "type": "function",
                "function": {
                    "name": "morning_brief",
                    "description": (
                        "Compose the daily brief: today's calendar, scheduled "
                        "check-ins/alarms, unread emails. Use when the user asks "
                        "'מה היום', 'what's my day', or for a summary of today."
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            _brief,
        ),
    }
