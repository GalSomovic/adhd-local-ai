"""Deterministic check-in + escalation engine. No LLM anywhere in this file."""

import logging
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

    def start(self):
        for row in self.conn.execute("SELECT * FROM checkins WHERE active = 1"):
            self._schedule(row)
        self.scheduler.add_job(self._tick, "interval", seconds=30, id="tick")
        self.scheduler.start()

    # -- check-in management (called by the skills layer) --

    def create_checkin(self, question, repeat, at_time=None, at_iso=None,
                       window_minutes=None, kind="checkin"):
        window = window_minutes or config.DEFAULT_WINDOW_MINUTES
        cur = self.conn.execute(
            "INSERT INTO checkins (question, repeat, at_time, at_iso, window_minutes, kind) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (question, repeat, at_time, at_iso, window, kind),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM checkins WHERE id = ?", (cur.lastrowid,)).fetchone()
        self._schedule(row)
        return dict(row)

    def list_checkins(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM checkins WHERE active = 1")]

    def cancel_checkin(self, checkin_id):
        self.conn.execute("UPDATE checkins SET active = 0 WHERE id = ?", (checkin_id,))
        self.conn.commit()
        job = self.scheduler.get_job(f"checkin-{checkin_id}")
        if job:
            job.remove()
        return {"cancelled": checkin_id}

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
        return len(open_rows)

    async def _tick(self):
        now = datetime.now(config.TZ)
        for row in self.conn.execute("SELECT * FROM pending WHERE status = 'waiting'"):
            if datetime.fromisoformat(row["deadline"]) <= now:
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
            await self.send_message(f"כיבית את השעון המעורר ⏰✅ — {row['question']}")
        elif status.get("expired"):
            if row["status"] == "escalated":
                await self._escalate(row, "realarmed")
            else:
                self.conn.execute(
                    "UPDATE pending SET status = 'missed' WHERE id = ?", (row["id"],)
                )
                self.conn.commit()
                await self.send_message(f"⚠️ גם השעון המעורר השני לא נענה: {row['question']}")
