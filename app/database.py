"""
Thin SQLite data layer.

v1 SIMPLIFICATION: SQLite, not Postgres. Fine for one tradesperson and low
volume; revisit once there are multiple clients with concurrent write load
(SQLite's single-writer lock will start to hurt at that point).

Uses the stdlib `sqlite3` module directly rather than an ORM -- there are
only three small tables and a handful of queries, so an ORM would be more
machinery than the problem needs at this stage.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_sid TEXT UNIQUE NOT NULL,
    from_number TEXT NOT NULL,
    to_number TEXT NOT NULL,
    initial_status TEXT,
    dial_call_status TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_number TEXT NOT NULL,
    channel TEXT NOT NULL,
    source_event TEXT NOT NULL,
    related_call_sid TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    direction TEXT NOT NULL,
    channel TEXT NOT NULL,
    from_number TEXT NOT NULL,
    to_number TEXT NOT NULL,
    body TEXT,
    message_sid TEXT,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection():
    Path(config.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def create_call(call_sid: str, from_number: str, to_number: str, initial_status: str) -> int:
    """Log an inbound call. Idempotent on call_sid so Twilio webhook retries
    don't create duplicate rows."""
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO calls (call_sid, from_number, to_number, initial_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(call_sid) DO UPDATE SET
                initial_status = excluded.initial_status,
                updated_at = excluded.updated_at
            """,
            (call_sid, from_number, to_number, initial_status, now, now),
        )
        row = conn.execute("SELECT id FROM calls WHERE call_sid = ?", (call_sid,)).fetchone()
        return row["id"]


def update_call_status(call_sid: str, dial_call_status: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE calls SET dial_call_status = ?, updated_at = ? WHERE call_sid = ?",
            (dial_call_status, _now(), call_sid),
        )


def get_call(call_sid: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM calls WHERE call_sid = ?", (call_sid,)).fetchone()
        return dict(row) if row else None


def get_or_create_open_conversation(
    customer_number: str,
    channel: str,
    source_event: str,
    related_call_sid: str | None = None,
) -> int:
    """Reuse the customer's existing open conversation if there is one,
    otherwise open a new one. Keeps a back-and-forth text exchange (or a
    missed call followed by a text) as a single tracked conversation rather
    than one row per inbound event.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM conversations WHERE customer_number = ? AND status = 'open' "
            "ORDER BY id DESC LIMIT 1",
            (customer_number,),
        ).fetchone()
        if row:
            return row["id"]

        now = _now()
        cur = conn.execute(
            """
            INSERT INTO conversations
                (customer_number, channel, source_event, related_call_sid, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'open', ?, ?)
            """,
            (customer_number, channel, source_event, related_call_sid, now, now),
        )
        return cur.lastrowid


def get_conversation(conversation_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        return dict(row) if row else None


def create_message(
    conversation_id: int,
    direction: str,
    channel: str,
    from_number: str,
    to_number: str,
    body: str | None,
    message_sid: str | None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages
                (conversation_id, direction, channel, from_number, to_number, body, message_sid, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, direction, channel, from_number, to_number, body, message_sid, _now()),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (_now(), conversation_id),
        )
        return cur.lastrowid


def list_messages(conversation_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]
