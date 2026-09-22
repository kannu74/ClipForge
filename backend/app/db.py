"""
SQLite storage for project metadata. Deliberately plain sqlite3 (no ORM) --
the schema is small and this keeps the dependency footprint minimal. If the
schema grows significantly in a later phase, revisit this decision rather
than accumulating migrations by hand.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'general_creator',
    source_type TEXT,              -- 'local' | 'youtube' | NULL (not set yet)
    source_reference TEXT,         -- original filename or YouTube URL
    status TEXT NOT NULL DEFAULT 'created',  -- created|ingesting|ready|transcribing|analyzing|ranking|rendering|error
    preset_id TEXT,
    settings_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',  -- ffprobe-derived: duration, resolution, fps, codecs...
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    settings.ensure_dirs()
    conn = sqlite3.connect(settings.db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        # WAL lets the UI keep reading while a background job writes progress.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    from app.jobs import init_jobs_table

    init_jobs_table()


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_project(
    *,
    name: str,
    content_type: str,
    settings_json: dict[str, Any] | None = None,
) -> sqlite3.Row:
    project_id = str(uuid.uuid4())
    now = _now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO projects (id, name, content_type, status, settings_json, created_at, updated_at)
            VALUES (?, ?, ?, 'created', ?, ?, ?)
            """,
            (project_id, name, content_type, json.dumps(settings_json or {}), now, now),
        )
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row


def list_projects() -> list[sqlite3.Row]:
    with connection() as conn:
        return conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()


def get_project(project_id: str) -> sqlite3.Row | None:
    with connection() as conn:
        return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


def update_project(project_id: str, **fields: Any) -> sqlite3.Row | None:
    if not fields:
        return get_project(project_id)
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [project_id]
    with connection() as conn:
        conn.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", values)
        return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


def delete_project(project_id: str) -> bool:
    with connection() as conn:
        cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return cur.rowcount > 0


def project_dir(project_id: str) -> Path:
    return settings.projects_dir / project_id
