"""SQLite persistence. Shared contract alongside models.py.

Tables:
  posts        Instagram posts already fetched/extracted (seen cache, no re-calls)
  events       events per source, upserted by Event.key()
  source_runs  per-run yield report (events found, unique, errors)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Event, Post

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "events.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    shortcode    TEXT PRIMARY KEY,
    account      TEXT NOT NULL,
    posted_at    TEXT NOT NULL,
    caption      TEXT,
    url          TEXT,
    image_path   TEXT,
    extracted_at TEXT,          -- NULL until sent to the model
    is_event     INTEGER        -- NULL until extracted
);
CREATE TABLE IF NOT EXISTS events (
    key          TEXT PRIMARY KEY,
    source_name  TEXT NOT NULL,
    date         TEXT NOT NULL,
    data         TEXT NOT NULL,  -- Event JSON
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
CREATE TABLE IF NOT EXISTS source_runs (
    run_at       TEXT NOT NULL,
    source_name  TEXT NOT NULL,
    n_events     INTEGER NOT NULL,
    n_unique     INTEGER,
    error        TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ---- posts ---------------------------------------------------------------

def post_seen(conn: sqlite3.Connection, shortcode: str) -> bool:
    return conn.execute("SELECT 1 FROM posts WHERE shortcode=?", (shortcode,)).fetchone() is not None


def save_post(conn: sqlite3.Connection, post: Post) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO posts (shortcode, account, posted_at, caption, url, image_path) "
        "VALUES (?,?,?,?,?,?)",
        (post.shortcode, post.account, post.posted_at, post.caption, post.url, post.image_path),
    )
    conn.commit()


def unextracted_posts(conn: sqlite3.Connection) -> list[Post]:
    rows = conn.execute(
        "SELECT shortcode, account, posted_at, caption, url, image_path FROM posts "
        "WHERE extracted_at IS NULL ORDER BY posted_at"
    ).fetchall()
    return [Post(**dict(r)) for r in rows]


def mark_extracted(conn: sqlite3.Connection, shortcode: str, is_event: bool) -> None:
    conn.execute(
        "UPDATE posts SET extracted_at=?, is_event=? WHERE shortcode=?",
        (_now(), int(is_event), shortcode),
    )
    conn.commit()


# ---- events --------------------------------------------------------------

def save_events(conn: sqlite3.Connection, events: list[Event]) -> None:
    now = _now()
    for ev in events:
        conn.execute(
            "INSERT INTO events (key, source_name, date, data, first_seen, last_seen) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET data=excluded.data, date=excluded.date, "
            "last_seen=excluded.last_seen",
            (ev.key(), ev.source_name, ev.date, json.dumps(ev.to_dict()), now, now),
        )
    conn.commit()


def upcoming_events(conn: sqlite3.Connection, today: str) -> list[Event]:
    """All stored events whose date (or end_date) is today or later. Not deduped."""
    rows = conn.execute(
        "SELECT data FROM events WHERE date >= ? OR json_extract(data, '$.end_date') >= ? "
        "ORDER BY date",
        (today, today),
    ).fetchall()
    return [Event.from_dict(json.loads(r["data"])) for r in rows]


# ---- yield report --------------------------------------------------------

def record_source_run(conn: sqlite3.Connection, source_name: str, n_events: int,
                      n_unique: int | None = None, error: str | None = None) -> None:
    conn.execute(
        "INSERT INTO source_runs (run_at, source_name, n_events, n_unique, error) VALUES (?,?,?,?,?)",
        (_now(), source_name, n_events, n_unique, error),
    )
    conn.commit()
