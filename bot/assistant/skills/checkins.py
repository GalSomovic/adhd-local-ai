def build(ctx):
    engine = ctx["engine"]

    async def create_checkin(question, repeat, at_time=None, at_iso=None, window_minutes=None):
        return engine.create_checkin(question, repeat, at_time, at_iso, window_minutes)

    async def set_alarm(label, repeat, at_time=None, at_iso=None):
        return engine.create_checkin(label, repeat, at_time, at_iso, kind="alarm")

    async def list_checkins():
        return {"checkins": engine.list_checkins()}

    async def cancel_checkin(checkin_id):
        return engine.cancel_checkin(int(checkin_id))

    return {
        "set_alarm": (
            {
                "type": "function",
                "function": {
                    "name": "set_alarm",
                    "description": (
                        "Set a שעון מעורר (wake-up alarm): at the given time the user's phone "
                        "rings at full volume (bypasses mute) and keeps re-alerting until "
                        "acknowledged. Use when the user wants an alarm / שעון מעורר / to be "
                        "woken or paged at a specific time. repeat='daily' with at_time='HH:MM', "
                        "or repeat='once' with at_iso='YYYY-MM-DDTHH:MM'."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "What the alarm is for, in the user's language"},
                            "repeat": {"type": "string", "enum": ["daily", "once"]},
                            "at_time": {"type": "string", "description": "HH:MM, for daily"},
                            "at_iso": {"type": "string", "description": "ISO datetime, for once"},
                        },
                        "required": ["label", "repeat"],
                    },
                },
            },
            set_alarm,
        ),
        "create_checkin": (
            {
                "type": "function",
                "function": {
                    "name": "create_checkin",
                    "description": (
                        "Create a check-in: the assistant asks the question at the given time "
                        "and escalates to a phone alarm if the user does not answer within "
                        "window_minutes. Use repeat='daily' with at_time='HH:MM' for recurring, "
                        "or repeat='once' with at_iso='YYYY-MM-DDTHH:MM' for one-off."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "What to ask, in the user's language"},
                            "repeat": {"type": "string", "enum": ["daily", "once"]},
                            "at_time": {"type": "string", "description": "HH:MM, for daily"},
                            "at_iso": {"type": "string", "description": "ISO datetime, for once"},
                            "window_minutes": {"type": "integer", "description": "Minutes to wait before the alarm"},
                        },
                        "required": ["question", "repeat"],
                    },
                },
            },
            create_checkin,
        ),
        "list_checkins": (
            {
                "type": "function",
                "function": {
                    "name": "list_checkins",
                    "description": "List all active check-ins with their ids and schedules.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            list_checkins,
        ),
        "cancel_checkin": (
            {
                "type": "function",
                "function": {
                    "name": "cancel_checkin",
                    "description": "Cancel an active check-in by id.",
                    "parameters": {
                        "type": "object",
                        "properties": {"checkin_id": {"type": "integer"}},
                        "required": ["checkin_id"],
                    },
                },
            },
            cancel_checkin,
        ),
    }
