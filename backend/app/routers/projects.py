"""Project CRUD + per-project settings."""
from __future__ import annotations

from fastapi import APIRouter

from app import db, jobs, project_settings, storage
from app.errors import NotFoundError, ValidationFailedError
from app.logging_config import get_logger
from app.models import ProjectCreateRequest, ProjectOut
from app.routers.common import project_out, require_project

router = APIRouter(prefix="/api/projects", tags=["projects"])
logger = get_logger("routers.projects")


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreateRequest) -> ProjectOut:
    name = payload.name.strip()
    if not name:
        raise ValidationFailedError(
            "Project name can't be empty.", suggestion="Give the project a short, memorable name."
        )
    initial = project_settings.ProjectSettings()
    if payload.settings:
        try:
            initial = project_settings.ProjectSettings(
                **project_settings.deep_merge(initial.model_dump(), payload.settings)
            )
        except Exception as exc:
            raise ValidationFailedError("Some of those settings aren't valid.", detail=str(exc))

    row = db.create_project(name=name, content_type=payload.content_type.value, settings_json=initial.model_dump())
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
    return project_out(row)


@router.get("", response_model=list[ProjectOut])
def list_projects() -> list[ProjectOut]:
    return [project_out(r) for r in db.list_projects()]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str) -> ProjectOut:
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError(
            "That project doesn't exist.", suggestion="It may have been deleted. Refresh your project list."
        )
    return project_out(row)


@router.patch("/{project_id}", response_model=ProjectOut)
def rename_project(project_id: str, payload: dict) -> ProjectOut:
    require_project(project_id)
    fields = {}
    if "name" in payload:
        name = str(payload["name"]).strip()
        if not name:
            raise ValidationFailedError("Project name can't be empty.")
        fields["name"] = name[:200]
    if "content_type" in payload:
        from app.models import ContentType

        try:
            fields["content_type"] = ContentType(payload["content_type"]).value
        except ValueError:
            raise ValidationFailedError("Unknown content type.")
    row = db.update_project(project_id, **fields)
    return project_out(row)


@router.get("/{project_id}/settings")
def get_settings(project_id: str) -> dict:
    require_project(project_id)
    return project_settings.load(project_id).model_dump()


@router.patch("/{project_id}/settings")
def patch_settings(project_id: str, patch: dict) -> dict:
    require_project(project_id)
    try:
        return project_settings.update(project_id, patch).model_dump()
    except Exception as exc:
        raise ValidationFailedError("Some of those settings aren't valid.", detail=str(exc))


@router.delete("/{project_id}", status_code=204, response_model=None)
def delete_project(project_id: str) -> None:
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("That project doesn't exist.")
    jobs.cancel_project_jobs(project_id)
    db.delete_project(project_id)
    storage.delete_project_storage(project_id)
    logger.info("Deleted project %s", project_id)
    return None
