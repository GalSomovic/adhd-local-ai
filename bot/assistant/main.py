import asyncio
import logging

from nio import AsyncClient, LoginResponse, RoomCreateResponse, RoomMessageText

from . import config, pushover, store
from .engine import Engine
from .llm import LLM
from .skills import build_registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("assistant")

HELP = """\
פקודות ישירות (עוקפות את המודל):
!checkins — רשימת צ'ק-אינים פעילים
!cancel <id> — ביטול צ'ק-אין
!testalarm — בדיקת מסלול האזעקה מקצה לקצה
!help — ההודעה הזאת
כל הודעה אחרת הולכת לעוזר עצמו."""


class Bot:
    def __init__(self):
        self.conn = store.connect()
        self.client = AsyncClient(config.MATRIX_HOMESERVER, config.MATRIX_USER)
        self.room_id = None
        self.engine = Engine(self.conn, self.send)
        schemas, dispatch = build_registry({"engine": self.engine})
        self.llm = LLM(schemas, dispatch)

    async def send(self, text: str):
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

        resolved = await self.engine.resolve_pending()
        if text.startswith("!"):
            await self._command(text)
            return
        if resolved and len(text) < 80:
            await self.send("רשמתי ✅")
        reply = await self.llm.chat(text)
        await self.send(reply)

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
                f"[{r['id']}] {r['question']} — {r['repeat']} "
                f"{r['at_time'] or r['at_iso']} (חלון {r['window_minutes']} דק')"
                for r in rows
            ]
            await self.send("\n".join(lines))
        elif cmd == "!cancel" and arg.isdigit():
            self.engine.cancel_checkin(int(arg))
            await self.send(f"בוטל [{arg}] ✅")
        elif cmd == "!testalarm":
            receipt = await pushover.send_emergency("בדיקת אזעקה — תאשר בטלפון")
            await self.send(f"אזעקת בדיקה נשלחה 🚨 (receipt {receipt})")
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
