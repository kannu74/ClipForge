"""
Background jobs.

Downloading, transcribing and rendering take minutes, so they run on worker
threads instead of inside the HTTP request. Job state lives in SQLite so the
UI can poll it (and so it survives a page refresh). Two queues:

  - "main":   download -> transcribe -> analyze (CPU/GPU heavy, one at a time)
  - "render": clip renders, so a finished clip can be re-rendered after an
              edit without waiting behind a long transcription.

A job function receives a JobContext and reports progress with
ctx.update(progress, message). Raising ClipForgeError marks the job failed
with its plain-language message + suggestion; any other exception is logged
with its traceback and shown to the user as a generic, non-technical error.
If the server restarts mid-job, the job is marked failed ("interrupted")
at next startup rather than hanging forever in "running".
"""
from __future__ import annotations

import json
import threading
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from app import db
from app.errors import ClipForgeError
from app.logging_config import get_logger

logger = get_logger("jobs")

JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    kind TEXT NOT NULL,
    queue TEXT NOT NULL DEFAULT 'main',
    status TEXT NOT NULL,              -- queued|running|done|failed|cancelled
    progress REAL NOT NULL DEFAULT 0,
    stage TEXT,
    message TEXT,
    error TEXT,
    suggestion TEXT,
    params_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id, created_at);
"""

ACTIVE = ("queued", "running")


class JobCancelled(BaseException):
    """BaseException on purpose: generic `except Exception` handlers (e.g.
    around yt-dlp, which calls our progress hook) must not swallow a cancel."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobContext:
    job_id: str
    project_id: str | None
    params: dict

    def update(self, progress: float | None = None, message: str | None = None, stage: str | None = None) -> None:
        fields: dict[str, Any] = {}
        if progress is not None:
            fields["progress"] = float(max(0.0, min(progress, 1.0)))
        if message is not None:
            fields["message"] = message
        if stage is not None:
            fields["stage"] = stage
        if fields:
            _update(self.job_id, **fields)
        if is_cancel_requested(self.job_id):
            raise JobCancelled()

    def sub(self, lo: float, hi: float, stage: str | None = None) -> Callable[[float, str], None]:
        """A progress callback mapping 0..1 onto [lo, hi] of this job."""

        def cb(frac: float, message: str = "") -> None:
            self.update(lo + (hi - lo) * max(0.0, min(frac, 1.0)), message or None, stage)

        return cb


JobFn = Callable[[JobContext], Any]
_REGISTRY: dict[str, JobFn] = {}
_cancel_flags: set[str] = set()
_lock = threading.Lock()
_wakeups: dict[str, threading.Event] = {}
_workers: dict[str, threading.Thread] = {}
_stop = threading.Event()


def register(kind: str) -> Callable[[JobFn], JobFn]:
    def deco(fn: JobFn) -> JobFn:
        _REGISTRY[kind] = fn
        return fn

    return deco


def init_jobs_table() -> list[dict]:
    """Create the table and fail any job a previous run left unfinished.
    Returns those jobs so the caller can reset clip/project state."""
    with db.connection() as conn:
        conn.executescript(JOBS_SCHEMA)
        stale = [
            _row_to_dict(r)
            for r in conn.execute("SELECT * FROM jobs WHERE status IN ('running','queued')").fetchall()
        ]
        # Anything still "running"/"queued" from a previous process can't be
        # resumed mid-flight -- say so instead of leaving it spinning.
        conn.execute(
            "UPDATE jobs SET status='failed', error=?, suggestion=?, updated_at=? WHERE status IN ('running','queued')",
            (
                "This job was interrupted because ClipForge was closed or restarted.",
                "Start it again -- finished steps (download, transcript) are reused, so it resumes quickly.",
                _now(),
            ),
        )
    return stale


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["params"] = json.loads(d.pop("params_json") or "{}")
    d["result"] = json.loads(d.pop("result_json")) if d.get("result_json") else None
    return d


def _update(job_id: str, **fields: Any) -> None:
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with db.connection() as conn:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", [*fields.values(), job_id])


def enqueue(kind: str, project_id: str | None, params: dict | None = None, queue: str = "main") -> dict:
    if kind not in _REGISTRY:
        raise ValueError(f"Unknown job kind: {kind}")
    job_id = uuid.uuid4().hex[:16]
    now = _now()
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO jobs (id, project_id, kind, queue, status, progress, message, params_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?)",
            (job_id, project_id, kind, queue, "Waiting to start...", json.dumps(params or {}), now, now),
        )
    ev = _wakeups.get(queue)
    if ev:
        ev.set()
    return get_job(job_id)  # type: ignore[return-value]


def get_job(job_id: str) -> dict | None:
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_jobs(project_id: str, limit: int = 50) -> list[dict]:
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE project_id = ? ORDER BY created_at DESC LIMIT ?", (project_id, limit)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def active_jobs(project_id: str, kind: str | None = None) -> list[dict]:
    q = "SELECT * FROM jobs WHERE project_id = ? AND status IN ('queued','running')"
    args: list[Any] = [project_id]
    if kind:
        q += " AND kind = ?"
        args.append(kind)
    with db.connection() as conn:
        rows = conn.execute(q + " ORDER BY created_at", args).fetchall()
    return [_row_to_dict(r) for r in rows]


_cancel_hooks: dict[str, Callable[[dict], None]] = {}


def on_cancel_queued(kind: str) -> Callable[[Callable[[dict], None]], Callable[[dict], None]]:
    """Register cleanup for a job that is cancelled before it ever started
    (e.g. reset a clip's "queued" render badge)."""

    def deco(fn: Callable[[dict], None]) -> Callable[[dict], None]:
        _cancel_hooks[kind] = fn
        return fn

    return deco


def request_cancel(job_id: str) -> dict | None:
    job = get_job(job_id)
    if not job:
        return None
    if job["status"] == "queued":
        with db.connection() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status='cancelled', message='Cancelled.', updated_at=? WHERE id=? AND status='queued'",
                (_now(), job_id),
            )
            claimed_meanwhile = cur.rowcount == 0
        if not claimed_meanwhile:
            hook = _cancel_hooks.get(job["kind"])
            if hook:
                try:
                    hook(job)
                except Exception:  # pragma: no cover
                    logger.exception("Cancel hook failed for job %s", job_id)
            return get_job(job_id)
        job = get_job(job_id) or job
    if job["status"] == "running":
        with _lock:
            _cancel_flags.add(job_id)
        _update(job_id, message="Cancelling...")
    return get_job(job_id)


def is_cancel_requested(job_id: str) -> bool:
    with _lock:
        return job_id in _cancel_flags


def cancel_project_jobs(project_id: str) -> None:
    for job in active_jobs(project_id):
        request_cancel(job["id"])


def _claim_next(queue: str) -> dict | None:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE queue = ? AND status = 'queued' ORDER BY created_at LIMIT 1", (queue,)
        ).fetchone()
        if row is None:
            return None
        cur = conn.execute(
            "UPDATE jobs SET status='running', updated_at=? WHERE id=? AND status='queued'", (_now(), row["id"])
        )
        if cur.rowcount != 1:
            return None
    return get_job(row["id"])


def run_job_now(job: dict) -> None:
    """Execute one claimed job synchronously (used by workers and tests)."""
    fn = _REGISTRY[job["kind"]]
    ctx = JobContext(job_id=job["id"], project_id=job["project_id"], params=job["params"])
    try:
        result = fn(ctx)
        _update(
            job["id"],
            status="done",
            progress=1.0,
            message="Done.",
            result_json=json.dumps(result) if result is not None else None,
        )
    except JobCancelled:
        _update(job["id"], status="cancelled", message="Cancelled.")
    except ClipForgeError as exc:
        logger.error("Job %s (%s) failed: %s (detail=%s)", job["id"], job["kind"], exc.message, exc.detail)
        _update(job["id"], status="failed", error=exc.message, suggestion=exc.suggestion, message=exc.message)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Job %s (%s) crashed:\n%s", job["id"], job["kind"], traceback.format_exc())
        _update(
            job["id"],
            status="failed",
            error="Something went wrong while processing this step.",
            suggestion="Check data/logs/clipforge.log for details, then try again.",
            message=f"Failed ({type(exc).__name__}).",
        )
    finally:
        with _lock:
            _cancel_flags.discard(job["id"])


def _worker(queue: str) -> None:
    ev = _wakeups[queue]
    while not _stop.is_set():
        try:
            job = _claim_next(queue)
        except Exception:  # pragma: no cover - db hiccup
            logger.exception("Job queue %s: claim failed", queue)
            job = None
        if job is None:
            ev.wait(timeout=1.0)
            ev.clear()
            continue
        logger.info("Job %s started: %s (project %s)", job["id"], job["kind"], job["project_id"])
        run_job_now(job)


def start_workers(queues: tuple[str, ...] = ("main", "render")) -> None:
    _stop.clear()
    for q in queues:
        if q in _workers and _workers[q].is_alive():
            continue
        _wakeups[q] = threading.Event()
        t = threading.Thread(target=_worker, args=(q,), name=f"clipforge-{q}-worker", daemon=True)
        _workers[q] = t
        t.start()


def stop_workers() -> None:
    _stop.set()
    for ev in _wakeups.values():
        ev.set()


def wait_idle(timeout: float = 60.0) -> bool:
    """Block until no job is queued or running (tests / CLI)."""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        with db.connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
        if n == 0:
            return True
        time.sleep(0.1)
    return False
