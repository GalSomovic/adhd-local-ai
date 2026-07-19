def build(ctx):
    engine = ctx["engine"]

    async def create_checkin(question, repeat=None, at_time=None, at_iso=None,
                             window_minutes=None, in_minutes=None):
        return engine.create_checkin(question, repeat or "once", at_time, at_iso,
                                     window_minutes, in_minutes=in_minutes)

    async def set_alarm(label, repeat=None, at_time=None, at_iso=None, in_minutes=None):
        return engine.create_checkin(label, repeat or "once", at_time, at_iso,
                                     kind="alarm", in_minutes=in_minutes)

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
                        "or repeat='once' with at_iso='YYYY-MM-DDTHH:MM'. For RELATIVE "
                        "times ('in 20 minutes', 'בעוד שעתיים') pass in_minutes and "
                        "NOTHING else — never compute the timestamp yourself."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "What the alarm is for, in the user's language"},
                            "repeat": {"type": "string", "enum": ["daily", "once"]},
                            "at_time": {"type": "string", "description": "HH:MM, for daily"},
                            "at_iso": {"type": "string", "description": "ISO datetime, for once at an absolute time"},
                            "in_minutes": {"type": "number", "description": "Minutes from now, for relative times ('in 20 minutes' -> 20)"},
                        },
                        "required": ["label"],
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
                        "repeat='once' with at_iso='YYYY-MM-DDTHH:MM' for one-off at an "
                        "absolute time, or in_minutes alone for relative times — never "
                        "compute the timestamp yourself."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "What to ask, in the user's language"},
                            "repeat": {"type": "string", "enum": ["daily", "once"]},
                            "at_time": {"type": "string", "description": "HH:MM, for daily"},
                            "at_iso": {"type": "string", "description": "ISO datetime, for once at an absolute time"},
                            "in_minutes": {"type": "number", "description": "Minutes from now, for relative times"},
                            "window_minutes": {"type": "integer", "description": "Minutes to wait before the שעון מעורר fires"},
                        },
                        "required": ["question"],
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
