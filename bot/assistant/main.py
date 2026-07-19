import asyncio
import logging
import re
from datetime import datetime

from nio import AsyncClient, LoginResponse, RoomCreateResponse, RoomMessageText

from . import config, gapi, pushover, store
from .engine import Engine
from .llm import LLM
from .skills import build_registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("assistant")

HELP = """\
פקודות ישירות (עוקפות את המודל):
!checkins — רשימת צ'ק-אינים ושעונים מעוררים פעילים
!cancel <id> — ביטול לפי מזהה
!testalarm — בדיקת שעון מעורר מקצה לקצה
!brief — הברִיף של היום (יומן + מיילים + קבועים)
!send — שליחת טיוטת המייל הממתינה | !discard — ביטולה
!help — ההודעה הזאת
כל הודעה אחרת הולכת לעוזר עצמו."""


class Bot:
    def __init__(self):
        self.conn = store.connect()
        self.client = AsyncClient(config.MATRIX_HOMESERVER, config.MATRIX_USER)
        self.room_id = None
        self.engine = Engine(self.conn, self.send)
        schemas, dispatch = build_registry({"engine": self.engine, "conn": self.conn})
        self.llm = LLM(schemas, dispatch)
        if gapi.enabled():
            self._wire_google()

    def _wire_google(self):
        from .skills import brief, gcal, gtasks

        async def on_event(action, pending_id, question, kind):
            if action == "fired":
                icon = "⏰" if kind == "alarm" else "❓"
                task_id = await gtasks.add_task(self.conn, f"{icon} {question}")
                self.conn.execute(
                    "UPDATE pending SET gtask_id = ? WHERE id = ?", (task_id, pending_id)
                )
                self.conn.commit()
            else:
                row = self.conn.execute(
                    "SELECT gtask_id FROM pending WHERE id = ?", (pending_id,)
                ).fetchone()
                if row and row["gtask_id"]:
                    await gtasks.complete_task(self.conn, row["gtask_id"])

        self.engine.on_event = on_event
        self.engine.busy_checker = gcal.busy_now
        if config.BRIEF_TIME:
            hour, minute = config.BRIEF_TIME.split(":")

            async def send_brief():
                await self.send(await brief.build_brief(self.engine))

            self.engine.scheduler.add_job(
                send_brief, "cron", hour=int(hour), minute=int(minute), id="morning-brief"
            )

    async def send(self, text: str):
        log.info("bot: %s", text)
        await self.client.room_send(
            self.room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": text},
        )

    async def _login(self):
        token = store.kv_get(self.conn, "matrix_token")
        device_id = store.kv_get(self.conn, "matrix_device_id")
        if token and device_id:
            self.client.restore_login(config.MATRIX_USER, device_id, token)
            return
        resp = await self.client.login(config.MATRIX_PASSWORD, device_name="assistant-bot")
        if not isinstance(resp, LoginResponse):
            raise RuntimeError(f"matrix login failed: {resp}")
        store.kv_set(self.conn, "matrix_token", resp.access_token)
        store.kv_set(self.conn, "matrix_device_id", resp.device_id)

    async def _ensure_room(self):
        self.room_id = store.kv_get(self.conn, "room_id")
        if self.room_id:
            return
        resp = await self.client.room_create(
            name="ADHD Assistant",
            invite=[config.OWNER_MXID],
            is_direct=True,
        )
        if not isinstance(resp, RoomCreateResponse):
            raise RuntimeError(f"room create failed: {resp}")
        self.room_id = resp.room_id
        store.kv_set(self.conn, "room_id", self.room_id)
        log.info("created room %s and invited %s", self.room_id, config.OWNER_MXID)

    async def _on_message(self, room, event: RoomMessageText):
        if room.room_id != self.room_id or event.sender != config.OWNER_MXID:
            return
        text = event.body.strip()
        log.info("owner: %s", text)
        self.engine.anchor_time = datetime.now(config.TZ)

        resolved = await self.engine.resolve_pending()
        if text.startswith("!"):
            await self._command(text)
            return
        fast = self._fast_alarm(text)
        if fast:
            await self.send(fast)
            return
        if resolved and len(text) < 80:
            await self.send("רשמתי ✅")
        reply = await self.llm.chat(text)
        await self.send(reply)

    def _fast_alarm(self, text):
        """Deterministic parse of the golden alarm phrasings — no LLM involved."""
        result = None
        m = (re.search(r"תעיר\s+אותי\s+ב-?\s*(\d{1,2}:\d{2})", text)
             or re.search(r"wake me(?: up)? at (\d{1,2}:\d{2})", text, re.I))
        if m:
            result = self.engine.create_checkin(text, "once", at_time=m.group(1), kind="alarm")
        else:
            m = (re.search(r"תעיר\s+אותי\s+ב?עוד\s+(\d+)\s*(דק|שע)", text)
                 or re.search(r"wake me(?: up)? in (\d+)\s*(min|m\b|hour|h\b)", text, re.I))
            if m:
                mins = int(m.group(1)) * (60 if m.group(2).startswith(("שע", "h")) else 1)
                result = self.engine.create_checkin(text, "once", in_minutes=mins, kind="alarm")
        if not result:
            return None
        if result.get("error"):
            return f"⚠️ {result['error']}"
        return f"נקבע ⏰ ל-{result['fires_at']}"

    async def _command(self, text: str):
        cmd, _, arg = text.partition(" ")
        if cmd == "!help":
            await self.send(HELP)
        elif cmd == "!checkins":
            rows = self.engine.list_checkins()
            if not rows:
                await self.send("אין צ'ק-אינים פעילים")
                return
            lines = [
                f"[{r['id']}] {'⏰' if r['kind'] == 'alarm' else '❓'} {r['question']} — "
                f"{r['repeat']} {r['at_time'] or r['at_iso']}"
                + ("" if r["kind"] == "alarm" else f" (חלון {r['window_minutes']} דק')")
                for r in rows
            ]
            await self.send("\n".join(lines))
        elif cmd == "!cancel" and arg.isdigit():
            self.engine.cancel_checkin(int(arg))
            await self.send(f"בוטל [{arg}] ✅")
        elif cmd == "!testalarm":
            receipt = await pushover.send_emergency("בדיקת שעון מעורר — תאשר בטלפון")
            await self.send(f"שעון מעורר לבדיקה נשלח ⏰ (receipt {receipt})")
        elif cmd == "!brief" and gapi.enabled():
            from .skills import brief
            await self.send(await brief.build_brief(self.engine))
        elif cmd == "!send" and gapi.enabled():
            from .skills import gmail_skill
            await self.send(await gmail_skill.send_staged(self.conn))
        elif cmd == "!discard" and gapi.enabled():
            from .skills import gmail_skill
            await self.send(gmail_skill.discard_staged(self.conn))
        else:
            await self.send(HELP)

    async def run(self):
        await self._login()
        await self._ensure_room()
        # first sync without callbacks so restarts don't replay old messages
        await self.client.sync(timeout=0, full_state=True)
        self.client.add_event_callback(self._on_message, RoomMessageText)
        self.engine.start()
        log.info("assistant up, syncing")
        await self.client.sync_forever(timeout=30000)


def main():
    asyncio.run(Bot().run())


if __name__ == "__main__":
    main()
