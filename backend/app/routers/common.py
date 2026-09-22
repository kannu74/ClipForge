"""Shared helpers for routers."""
from __future__ import annotations

from app import db, project_settings, storage
from app.errors import NotFoundError
from app.models import ProjectOut


def require_project(project_id: str):
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("That project doesn't exist.", suggestion="It may have been deleted.")
    return row


def project_out(row) -> ProjectOut:
    pid = row["id"]
    out = ProjectOut.from_row(
        row,
        has_transcript=storage.transcript_path(pid).exists(),
        has_moments=storage.moments_path(pid).exists(),
        has_clips=storage.clips_path(pid).exists(),
    )
    out.settings = project_settings.load(pid).model_dump()
    return out
