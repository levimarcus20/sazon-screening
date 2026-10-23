"""SQLite persistence.

A candidate is stored as one JSON document (the full Pydantic model) plus a few
indexed columns used for filtering in the dashboard. Messages and interview
bookings have their own tables. One short-lived connection per operation keeps
this safe to use from FastAPI's worker threads.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .models import Candidate, Message

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    recruiter_status TEXT NOT NULL,
    city TEXT,
    country TEXT,
    full_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    doc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_updated ON candidates(updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    meta TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_candidate ON messages(candidate_id, created_at);

CREATE TABLE IF NOT EXISTS interview_bookings (
    city_id TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    PRIMARY KEY (city_id, starts_at)
);
"""


class Storage:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- candidates ---------------------------------------------------------

    def save_candidate(self, c: Candidate) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO candidates (id, status, recruiter_status, city, country, full_name,
                                           created_at, updated_at, doc)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     status=excluded.status, recruiter_status=excluded.recruiter_status,
                     city=excluded.city, country=excluded.country, full_name=excluded.full_name,
                     updated_at=excluded.updated_at, doc=excluded.doc""",
                (c.id, c.status, c.recruiter_status, c.data.city, c.data.country, c.data.full_name,
                 c.created_at.isoformat(), c.updated_at.isoformat(), c.model_dump_json()),
            )

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        with self._conn() as conn:
            row = conn.execute("SELECT doc FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
        return Candidate.model_validate_json(row["doc"]) if row else None

    def list_candidates(self) -> list[Candidate]:
        with self._conn() as conn:
            rows = conn.execute("SELECT doc FROM candidates ORDER BY updated_at DESC").fetchall()
        return [Candidate.model_validate_json(r["doc"]) for r in rows]

    def delete_candidate(self, candidate_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM candidates WHERE id = ?", (candidate_id,))

    # -- messages -----------------------------------------------------------

    def add_message(self, m: Message) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages (id, candidate_id, role, content, created_at, meta) VALUES (?, ?, ?, ?, ?, ?)",
                (m.id, m.candidate_id, m.role, m.content, m.created_at.isoformat(), json.dumps(m.meta, default=str)),
            )

    def update_message_meta(self, message_id: str, meta: dict) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE messages SET meta = ? WHERE id = ?", (json.dumps(meta, default=str), message_id))

    def get_messages(self, candidate_id: str) -> list[Message]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE candidate_id = ? ORDER BY created_at, rowid", (candidate_id,)
            ).fetchall()
        return [
            Message(id=r["id"], candidate_id=r["candidate_id"], role=r["role"], content=r["content"],
                    created_at=datetime.fromisoformat(r["created_at"]), meta=json.loads(r["meta"]))
            for r in rows
        ]

    # -- interview bookings -------------------------------------------------

    def booked_slots(self, city_id: str) -> set[datetime]:
        with self._conn() as conn:
            rows = conn.execute("SELECT starts_at FROM interview_bookings WHERE city_id = ?", (city_id,)).fetchall()
        return {datetime.fromisoformat(r["starts_at"]) for r in rows}

    def book_slot(self, city_id: str, starts_at: datetime, candidate_id: str) -> bool:
        """Returns False if someone else took the slot in the meantime."""
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO interview_bookings (city_id, starts_at, candidate_id) VALUES (?, ?, ?)",
                    (city_id, starts_at.isoformat(), candidate_id),
                )
            return True
        except sqlite3.IntegrityError:
            return False
