import os
import sqlite3
from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    repeat TEXT NOT NULL CHECK (repeat IN ('daily', 'once')),
    at_time TEXT,
    at_iso TEXT,
    window_minutes INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS pending (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checkin_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    deadline TEXT NOT NULL,
    status TEXT NOT NULL,
    receipt TEXT
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(os.path.join(config.DATA_DIR, "assistant.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(checkins)")}
    if "kind" not in cols:
        conn.execute("ALTER TABLE checkins ADD COLUMN kind TEXT NOT NULL DEFAULT 'checkin'")
        conn.commit()
    return conn


def kv_get(conn, key):
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def kv_set(conn, key, value):
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
