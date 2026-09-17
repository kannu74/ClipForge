"""Transcription endpoints: kick off local speech-to-text, read the result,
and let the user manually correct a segment's text."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app import db, storage
from app.errors import NotFoundError, ValidationFailedError
from app.logging_config import get_logger
from app.models import SegmentEditRequest, TranscriptOut
from app.transcription import run_transcription, to_dict

router = APIRouter(prefix="/api/projects", tags=["transcription"])
logger = get_logger("routers.transcription")


def _require_project(project_id: str):
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("That project doesn't exist.", suggestion="It may have been deleted.")
    return row


@router.post("/{project_id}/transcribe", response_model=TranscriptOut)
def transcribe(project_id: str, model_size: str | None = None) -> TranscriptOut:
    row = _require_project(project_id)
    source = storage.find_source_file(project_id)
    if source is None:
        raise ValidationFailedError(
            "This project doesn't have a video yet.",
            suggestion="Upload a video or paste a YouTube URL before transcribing.",
        )

    db.update_project(project_id, status="transcribing")
    audio_scratch = storage.project_dir(project_id) / "transcript" / "_audio.wav"
    try:
        result = run_transcription(source, audio_scratch, model_size=model_size)
    except Exception as exc:
        db.update_project(project_id, status="error", error_message="Transcription failed.")
        raise

    created_at = datetime.now(timezone.utc).isoformat()
    payload = to_dict(project_id, result, created_at)
    storage.write_json(storage.transcript_path(project_id), payload)
    db.update_project(project_id, status="ready")
    logger.info("Transcript ready for project %s (%d segments)", project_id, len(payload["segments"]))
    return TranscriptOut(**payload)


@router.get("/{project_id}/transcript", response_model=TranscriptOut)
def get_transcript(project_id: str) -> TranscriptOut:
    _require_project(project_id)
    payload = storage.read_json(storage.transcript_path(project_id))
    if payload is None:
        raise NotFoundError(
            "No transcript yet.", suggestion="Transcribe this project's video first."
        )
    return TranscriptOut(**payload)


@router.patch("/{project_id}/transcript/segments/{segment_id}", response_model=TranscriptOut)
def edit_segment(project_id: str, segment_id: int, payload: SegmentEditRequest) -> TranscriptOut:
    _require_project(project_id)
    transcript = storage.read_json(storage.transcript_path(project_id))
    if transcript is None:
        raise NotFoundError("No transcript yet.", suggestion="Transcribe this project's video first.")

    found = False
    for seg in transcript["segments"]:
        if seg["id"] == segment_id:
            seg["text"] = payload.text
            seg["edited"] = True
            found = True
            break
    if not found:
        raise NotFoundError(f"No transcript segment with id {segment_id}.")

    storage.write_json(storage.transcript_path(project_id), transcript)
    logger.info("Edited segment %d in project %s", segment_id, project_id)
    return TranscriptOut(**transcript)
