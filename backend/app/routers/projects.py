"""Project CRUD endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app import db, storage
from app.errors import NotFoundError, ValidationFailedError
from app.logging_config import get_logger
from app.models import ProjectCreateRequest, ProjectOut

router = APIRouter(prefix="/api/projects", tags=["projects"])
logger = get_logger("routers.projects")


def _project_out(row) -> ProjectOut:
    has_transcript = storage.transcript_path(row["id"]).exists()
    has_moments = storage.moments_path(row["id"]).exists()
    has_clips = storage.clips_path(row["id"]).exists()
    return ProjectOut.from_row(row, has_transcript=has_transcript, has_moments=has_moments, has_clips=has_clips)


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreateRequest) -> ProjectOut:
    name = payload.name.strip()
    if not name:
        raise ValidationFailedError(
            "Project name can't be empty.", suggestion="Give the project a short, memorable name."
        )

    row = db.create_project(name=name, content_type=payload.content_type.value)
    storage.init_project_storage(row["id"])
    storage.write_manifest(
        row["id"],
        {
            "id": row["id"],
            "name": row["name"],
            "content_type": row["content_type"],
            "status": row["status"],
            "created_at": row["created_at"],
        },
    )
    logger.info("Created project %s (%s)", row["id"], row["name"])
    return _project_out(row)


@router.get("", response_model=list[ProjectOut])
def list_projects() -> list[ProjectOut]:
    return [_project_out(r) for r in db.list_projects()]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str) -> ProjectOut:
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError(
            "That project doesn't exist.", suggestion="It may have been deleted. Refresh your project list."
        )
    return _project_out(row)


@router.delete("/{project_id}", status_code=204, response_model=None)
def delete_project(project_id: str) -> None:
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("That project doesn't exist.")
    db.delete_project(project_id)
    storage.delete_project_storage(project_id)
    logger.info("Deleted project %s", project_id)
    return None
