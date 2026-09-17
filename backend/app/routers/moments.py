"""Moment detection endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import APIRouter

from app import db, storage
from app.audio_analysis import compute_energy_profile
from app.errors import NotFoundError, ValidationFailedError
from app.logging_config import get_logger
from app.media import extract_audio
from app.models import MomentsOut
from app.moments import detect_moments, moment_to_dict

router = APIRouter(prefix="/api/projects", tags=["moments"])
logger = get_logger("routers.moments")


def _require_project(project_id: str):
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("That project doesn't exist.", suggestion="It may have been deleted.")
    return row


@router.post("/{project_id}/detect-moments", response_model=MomentsOut)
def detect(project_id: str) -> MomentsOut:
    row = _require_project(project_id)
    transcript = storage.read_json(storage.transcript_path(project_id))
    if transcript is None:
        raise ValidationFailedError(
            "This project doesn't have a transcript yet.",
            suggestion="Transcribe the video before detecting moments.",
        )
    source = storage.find_source_file(project_id)
    if source is None:
        raise ValidationFailedError("This project doesn't have a video yet.")

    segments = [
        SimpleNamespace(start=s["start"], end=s["end"], text=s["text"]) for s in transcript["segments"]
    ]

    db.update_project(project_id, status="analyzing")
    audio_scratch = storage.project_dir(project_id) / "moments" / "_audio.wav"
    try:
        extract_audio(source, audio_scratch)
        energy_profile = compute_energy_profile(audio_scratch)
        moments, ollama_used = detect_moments(row["content_type"], segments, energy_profile)
    except Exception:
        db.update_project(project_id, status="error", error_message="Moment detection failed.")
        raise
    finally:
        audio_scratch.unlink(missing_ok=True)

    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "project_id": project_id,
        "content_type": row["content_type"],
        "moments": [moment_to_dict(m) for m in moments],
        "ollama_used": ollama_used,
        "created_at": created_at,
    }
    storage.write_json(storage.moments_path(project_id), payload)
    db.update_project(project_id, status="ready")
    logger.info(
        "Detected %d candidate moments for project %s (ollama_used=%s)",
        len(moments), project_id, ollama_used,
    )
    return MomentsOut(**payload)


@router.get("/{project_id}/moments", response_model=MomentsOut)
def get_moments(project_id: str) -> MomentsOut:
    _require_project(project_id)
    payload = storage.read_json(storage.moments_path(project_id))
    if payload is None:
        raise NotFoundError("No moments detected yet.", suggestion="Run moment detection first.")
    return MomentsOut(**payload)
