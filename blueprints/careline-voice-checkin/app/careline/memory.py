"""Cross-session memory for residents — the demo centerpiece.

SQLite stand-in for mem0/Letta with the same shape: facts extracted per call,
stamped with the call date, recalled into the next call's system prompt so the
agent can say "you mentioned your granddaughter's recital on Monday."
"""

import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("CARELINE_DB", os.path.join(os.path.dirname(__file__), "..", "careline.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    resident_id TEXT NOT NULL,
    fact TEXT NOT NULL,
    call_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calls (
    id TEXT PRIMARY KEY,
    resident_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    summary TEXT,
    concern_score INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    resident_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    severity TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_call(call_id: str, resident_id: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO calls (id, resident_id, started_at) VALUES (?, ?, ?)",
            (call_id, resident_id, now()),
        )


def end_call(call_id: str, summary: str, concern_score: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE calls SET ended_at = ?, summary = ?, concern_score = ? WHERE id = ?",
            (now(), summary, concern_score, call_id),
        )


def save_facts(resident_id: str, call_id: str, facts: list[str]) -> None:
    with _conn() as c:
        c.executemany(
            "INSERT INTO facts (resident_id, fact, call_id, created_at) VALUES (?, ?, ?, ?)",
            [(resident_id, f, call_id, now()) for f in facts],
        )


def recall(resident_id: str, limit: int = 12) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT fact, created_at FROM facts WHERE resident_id = ? ORDER BY id DESC LIMIT ?",
            (resident_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def recent_calls(resident_id: str, limit: int = 5) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, started_at, ended_at, summary, concern_score FROM calls "
            "WHERE resident_id = ? AND ended_at IS NOT NULL ORDER BY started_at DESC LIMIT ?",
            (resident_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def save_alert(resident_id: str, call_id: str, reason: str, severity: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO alerts (resident_id, call_id, reason, severity, created_at) VALUES (?, ?, ?, ?, ?)",
            (resident_id, call_id, reason, severity, now()),
        )


def list_alerts(limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
