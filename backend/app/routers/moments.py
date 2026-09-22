"""Moment detection endpoints."""
from __future__ import annotations


from fastapi import APIRouter

from app import db, pipeline, storage
from app.errors import NotFoundError, ValidationFailedError
from app.logging_config import get_logger
from app.models import MomentsOut

router = APIRouter(prefix="/api/projects", tags=["moments"])
logger = get_logger("routers.moments")


def _require_project(project_id: str):
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("That project doesn't exist.", suggestion="It may have been deleted.")
    return row


@router.post("/{project_id}/detect-moments", response_model=MomentsOut)
def detect(project_id: str) -> MomentsOut:
    _require_project(project_id)
    payload = pipeline.do_detect(project_id)
    return MomentsOut(**{k: v for k, v in payload.items() if k in MomentsOut.model_fields})


@router.get("/{project_id}/moments", response_model=MomentsOut)
def get_moments(project_id: str) -> MomentsOut:
    _require_project(project_id)
    payload = storage.read_json(storage.moments_path(project_id))
    if payload is None:
        raise NotFoundError("No moments detected yet.", suggestion="Run moment detection first.")
    return MomentsOut(**payload)
