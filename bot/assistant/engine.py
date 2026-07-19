"""Deterministic check-in + escalation engine. No LLM anywhere in this file."""

import logging
import re
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from . import config, pushover

log = logging.getLogger(__name__)

# pending.status lifecycle:
#   waiting -> answered            (reply in chat before the deadline)
#   waiting -> escalated           (deadline passed, Pushover emergency sent)
#   escalated -> answered          (reply in chat; live alarm gets cancelled)
#   escalated -> acked             (alarm acknowledged on the phone)
#   escalated -> realarmed         (first alarm expired unacknowledged, second sent)
#   realarmed -> answered | acked | missed


class Engine:
    def __init__(self, conn, send_message):
        self.conn = conn
        self.send_message = send_message  # async fn(text)
        self.scheduler = AsyncIOScheduler(timezone=config.TZ)
        # relative times ("in 3 minutes") count from when the user's message
        # arrived, not from when the LLM finished processing it
        self.anchor_time = None
        # optional integrations, wired by main when Google creds exist
        self.on_event = None      # async fn(action, pending_id, question, kind)
        self.busy_checker = None  # async fn() -> bool (in a meeting right now?)

    def start(self):
        for row in self.conn.execute("SELECT * FROM checkins WHERE active = 1").fetchall():
            try:
                self._schedule(row)
            except Exception:
                log.exception("unschedulable checkin %s — deactivating", row["id"])
                self.conn.execute("UPDATE checkins SET active = 0 WHERE id = ?", (row["id"],))
                self.conn.commit()
        self.scheduler.add_job(self._tick, "interval", seconds=30, id="tick")
        self.scheduler.start()

    # -- check-in management (called by the skills layer) --

    def create_checkin(self, question, repeat, at_time=None, at_iso=None,
                       window_minutes=None, kind="checkin", in_minutes=None):
        now = datetime.now(config.TZ)
        if repeat == "daily":
            if not at_time:
                return {"error": "daily schedule requires at_time as HH:MM"}
            fires_at = f"daily at {at_time}"
        else:
            repeat = "once"
            try:
                when = self._resolve_once(now, at_iso, at_time, in_minutes)
            except ValueError as exc:
                return {"error": str(exc)}
            at_iso = when.isoformat()
            fires_at = f"{when:%Y-%m-%d %H:%M}"
        window = window_minutes or config.DEFAULT_WINDOW_MINUTES
        cur = self.conn.execute(
            "INSERT INTO checkins (question, repeat, at_time, at_iso, window_minutes, kind) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (question, repeat, at_time, at_iso, window, kind),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM checkins WHERE id = ?", (cur.lastrowid,)).fetchone()
        self._schedule(row)
        icon = "⏰" if kind == "alarm" else "❓"
        return {**dict(row), "fires_at": fires_at,
                "confirm_to_user": f"נקבע {icon} ל-{fires_at} — {question}"}

    def list_checkins(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM checkins WHERE active = 1")]

    def cancel_checkin(self, checkin_id):
        self.conn.execute("UPDATE checkins SET active = 0 WHERE id = ?", (checkin_id,))
        self.conn.commit()
        job = self.scheduler.get_job(f"checkin-{checkin_id}")
        if job:
            job.remove()
        return {"cancelled": checkin_id}

    def _resolve_once(self, now, at_iso, at_time, in_minutes):
        """An absolute time always beats in_minutes — models tend to pass both."""
        clock = None
        if at_iso:
            try:
                when = datetime.fromisoformat(at_iso)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=config.TZ)
            except ValueError:
                clock = at_iso
        elif at_time:
            clock = at_time
        elif in_minutes is not None:
            if float(in_minutes) <= 0:
                raise ValueError("in_minutes must be positive")
            base = now
            if self.anchor_time and (now - self.anchor_time) < timedelta(minutes=10):
                base = self.anchor_time
            return max(base + timedelta(minutes=float(in_minutes)),
                       now + timedelta(seconds=10))
        else:
            raise ValueError("one-off schedule requires at_iso, at_time or in_minutes")
        if clock is not None:
            m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", clock)
            if not m:
                raise ValueError(
                    f"cannot parse time {clock!r} — use ISO datetime, HH:MM or in_minutes"
                )
            when = now.replace(hour=int(m[1]), minute=int(m[2]), second=0, microsecond=0)
            if when <= now:
                when += timedelta(days=1)  # next occurrence, like a real alarm clock
        if when <= now:
            raise ValueError(
                f"requested time {when:%Y-%m-%d %H:%M} is in the past — "
                f"it is now {now:%Y-%m-%d %H:%M}"
            )
        return when

    def _schedule(self, row):
        job_id = f"checkin-{row['id']}"
        if row["repeat"] == "daily":
            hour, minute = row["at_time"].split(":")
            trigger = CronTrigger(hour=int(hour), minute=int(minute), timezone=config.TZ)
        else:
            when = datetime.fromisoformat(row["at_iso"])
            if when.tzinfo is None:
                when = when.replace(tzinfo=config.TZ)
            if when < datetime.now(config.TZ):
                return
            trigger = DateTrigger(run_date=when)
        self.scheduler.add_job(
            self._fire, trigger, args=[row["id"]], id=job_id, replace_existing=True
        )

    # -- the escalation state machine --

    async def _fire(self, checkin_id):
        row = self.conn.execute(
            "SELECT * FROM checkins WHERE id = ? AND active = 1", (checkin_id,)
        ).fetchone()
        if not row:
            return
        now = datetime.now(config.TZ)
        is_alarm = row["kind"] == "alarm"
        deadline = now if is_alarm else now + timedelta(minutes=row["window_minutes"])
        cur = self.conn.execute(
            "INSERT INTO pending (checkin_id, question, sent_at, deadline, status) "
            "VALUES (?, ?, ?, ?, 'waiting')",
            (checkin_id, row["question"], now.isoformat(), deadline.isoformat()),
        )
        if row["repeat"] == "once":
            self.conn.execute("UPDATE checkins SET active = 0 WHERE id = ?", (checkin_id,))
        self.conn.commit()
        await self._emit("fired", cur.lastrowid, row["question"], row["kind"])
        if is_alarm:
            await self.send_message(f"⏰ שעון מעורר: {row['question']}")
            pending = self.conn.execute(
                "SELECT * FROM pending WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            await self._escalate(pending, "escalated")
        else:
            await self.send_message(
                f"❓ {row['question']}\n"
                f"(ענה תוך {row['window_minutes']} דקות, אחרת אני מפעיל שעון מעורר ⏰)"
            )

    async def _emit(self, action, pending_id, question, kind="checkin"):
        if not self.on_event:
            return
        try:
            await self.on_event(action, pending_id, question, kind)
        except Exception:
            log.exception("on_event(%s) failed", action)

    async def resolve_pending(self) -> int:
        """Owner replied in chat: settle everything open, cancelling live alarms."""
        open_rows = self.conn.execute(
            "SELECT * FROM pending WHERE status IN ('waiting', 'escalated', 'realarmed')"
        ).fetchall()
        for row in open_rows:
            if row["receipt"]:
                try:
                    await pushover.cancel(row["receipt"])
                except Exception:
                    log.exception("failed to cancel pushover receipt")
            self.conn.execute(
                "UPDATE pending SET status = 'answered' WHERE id = ?", (row["id"],)
            )
        self.conn.commit()
        for row in open_rows:
            await self._emit("closed", row["id"], row["question"])
        return len(open_rows)

    async def _tick(self):
        now = datetime.now(config.TZ)
        for row in self.conn.execute(
            "SELECT p.*, c.kind AS ckind FROM pending p "
            "LEFT JOIN checkins c ON c.id = p.checkin_id WHERE p.status = 'waiting'"
        ).fetchall():
            if datetime.fromisoformat(row["deadline"]) > now:
                continue
            if row["ckind"] == "checkin" and self.busy_checker:
                try:
                    if await self.busy_checker():
                        log.info("pending %s: in a meeting, holding the alarm", row["id"])
                        self.conn.execute(
                            "UPDATE pending SET deadline = ? WHERE id = ?",
                            ((now + timedelta(minutes=5)).isoformat(), row["id"]),
                        )
                        self.conn.commit()
                        continue
                except Exception:
                    log.exception("busy check failed, escalating anyway")
            await self._escalate(row, "escalated")
        for row in self.conn.execute(
            "SELECT * FROM pending WHERE status IN ('escalated', 'realarmed')"
        ):
            await self._check_receipt(row)

    async def _escalate(self, row, new_status):
        try:
            receipt = await pushover.send_emergency(row["question"])
        except Exception:
            log.exception("pushover send failed, will retry next tick")
            return
        self.conn.execute(
            "UPDATE pending SET status = ?, receipt = ? WHERE id = ?",
            (new_status, receipt, row["id"]),
        )
        self.conn.commit()
        log.info("escalated pending=%s to %s receipt=%s", row["id"], new_status, receipt)

    async def _check_receipt(self, row):
        try:
            status = await pushover.receipt_status(row["receipt"])
        except Exception:
            log.exception("receipt poll failed")
            return
        if status.get("acknowledged"):
            self.conn.execute("UPDATE pending SET status = 'acked' WHERE id = ?", (row["id"],))
            self.conn.commit()
            await self._emit("closed", row["id"], row["question"])
            await self.send_message(f"כיבית את השעון המעורר ⏰✅ — {row['question']}")
        elif status.get("expired"):
            if row["status"] == "escalated":
                await self._escalate(row, "realarmed")
            else:
                self.conn.execute(
                    "UPDATE pending SET status = 'missed' WHERE id = ?", (row["id"],)
                )
                self.conn.commit()
                await self._emit("closed", row["id"], row["question"])
                await self.send_message(f"⚠️ גם השעון המעורר השני לא נענה: {row['question']}")
