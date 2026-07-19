import json
import logging
from collections import deque
from datetime import datetime

import httpx

from . import config

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are Gal's personal ADHD assistant, running locally on his homelab.
You speak Hebrew when spoken to in Hebrew, English when spoken to in English.
Be short, warm and direct.

You have two scheduling tools — pick carefully:
- set_alarm = "שעון מעורר": rings Gal's phone at full volume at the given time,
  keeps ringing until he acknowledges. Use for alarms, wake-ups, "תעיר אותי",
  "שעון מעורר", or anything that must not be missable.
- create_checkin: asks a question in this chat at the given time; only if Gal
  does not answer within the window does it fall back to a שעון מעורר.
  Use for "תוודא ש...", "תשאל אותי אם...", habit tracking.

Vocabulary: the phone alert is always called "שעון מעורר" — never "אזעקה"
and never "התראת חירום". When the user asks for a reminder or alarm, always
call a tool — never just promise. Times are Israel time. Now: {now}.
"""

MAX_TOOL_ROUNDS = 5


class LLM:
    def __init__(self, tools_schema, tool_dispatch):
        self.tools_schema = tools_schema
        self.tool_dispatch = tool_dispatch  # async fn(name, args) -> dict
        self.history = deque(maxlen=20)

    async def chat(self, user_text: str) -> str:
        self.history.append({"role": "user", "content": user_text})
        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(
                    now=datetime.now(config.TZ).strftime("%A %Y-%m-%d %H:%M")
                ),
            },
            *self.history,
        ]
        for _ in range(MAX_TOOL_ROUNDS):
            msg = await self._complete(messages)
            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                reply = msg.get("content") or "🤖 (אין לי תשובה)"
                self.history.append({"role": "assistant", "content": reply})
                return reply
            messages.append(msg)
            for call in tool_calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"]["arguments"] or "{}")
                    result = await self.tool_dispatch(name, args)
                except Exception as exc:
                    log.exception("tool %s failed", name)
                    result = {"error": str(exc)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", name),
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
        return "עשיתי כמה פעולות אבל הסתבכתי בניסוח תשובה — תבדוק עם !checkins"

    async def _complete(self, messages) -> dict:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{config.OLLAMA_URL}/v1/chat/completions",
                json={
                    "model": config.OLLAMA_MODEL,
                    "messages": messages,
                    "tools": self.tools_schema,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]
