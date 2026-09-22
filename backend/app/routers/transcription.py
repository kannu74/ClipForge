"""Transcription endpoints: kick off local speech-to-text, read the result,
and let the user manually correct a segment's text."""
from __future__ import annotations

from fastapi import APIRouter

from app import db, storage
from app.errors import NotFoundError, ValidationFailedError
from app.logging_config import get_logger
from app.models import SegmentEditRequest, TranscriptOut
from app import pipeline

router = APIRouter(prefix="/api/projects", tags=["transcription"])
logger = get_logger("routers.transcription")


def _require_project(project_id: str):
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("That project doesn't exist.", suggestion="It may have been deleted.")
    return row


@router.post("/{project_id}/transcribe", response_model=TranscriptOut)
def transcribe(project_id: str, model_size: str | None = None) -> TranscriptOut:
    """Synchronous transcription (the UI uses the background "process" job)."""
    _require_project(project_id)
    payload = pipeline.do_transcribe(project_id, model_size=model_size, force=True)
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

    # Bump the revision so already-rendered clips show as needing a re-render
    # (their burned-in captions came from the old text).
    transcript["revision"] = int(transcript.get("revision") or 0) + 1
    storage.write_json(storage.transcript_path(project_id), transcript)
    logger.info("Edited segment %d in project %s", segment_id, project_id)
    return TranscriptOut(**transcript)
