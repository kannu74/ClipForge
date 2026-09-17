"""Video ingestion: local file upload and YouTube URL fetch, plus a media
streaming endpoint for the frontend's preview player."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import FileResponse

from app import db, storage
from app.errors import NotFoundError, ValidationFailedError
from app.logging_config import get_logger
from app.media import SUPPORTED_EXTENSIONS, probe
from app.models import ProjectOut, YoutubeIngestRequest
from app import youtube as youtube_module

router = APIRouter(prefix="/api/projects", tags=["ingest"])
logger = get_logger("routers.ingest")


def _require_project(project_id: str):
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("That project doesn't exist.", suggestion="It may have been deleted.")
    return row


def _project_out(row) -> ProjectOut:
    has_transcript = storage.transcript_path(row["id"]).exists()
    has_moments = storage.moments_path(row["id"]).exists()
    return ProjectOut.from_row(row, has_transcript=has_transcript, has_moments=has_moments)


def _finish_ingest(project_id: str, video_path: Path, source_type: str, source_reference: str) -> ProjectOut:
    metadata = probe(video_path)
    row = db.update_project(
        project_id,
        source_type=source_type,
        source_reference=source_reference,
        status="ready",
        metadata_json=json.dumps(metadata.to_dict()),
        error_message=None,
    )
    manifest = storage.read_manifest(project_id) or {}
    manifest.update(
        {
            "source_type": source_type,
            "source_reference": source_reference,
            "metadata": metadata.to_dict(),
        }
    )
    storage.write_manifest(project_id, manifest)
    logger.info("Ingested source for project %s (%s, %.1fs)", project_id, source_type, metadata.duration_seconds)
    return _project_out(row)


@router.post("/{project_id}/upload", response_model=ProjectOut)
async def upload_video(project_id: str, file: UploadFile = File(...)) -> ProjectOut:
    row = _require_project(project_id)

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValidationFailedError(
            f"'{suffix or 'that file'}' isn't a supported video format.",
            suggestion=f"Use one of: {', '.join(sorted(SUPPORTED_EXTENSIONS))}.",
        )

    src_dir = storage.source_dir(project_id)
    src_dir.mkdir(parents=True, exist_ok=True)
    # Clear any previous source so a project only ever has one active source.
    for existing in src_dir.iterdir():
        if existing.is_file():
            existing.unlink()

    dest = src_dir / f"source{suffix}"
    db.update_project(project_id, status="ingesting")
    try:
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
    finally:
        await file.close()

    try:
        return _finish_ingest(project_id, dest, "local", file.filename or dest.name)
    except Exception:
        db.update_project(project_id, status="error", error_message="Failed to process the uploaded video.")
        raise


@router.post("/{project_id}/youtube", response_model=ProjectOut)
def ingest_youtube(project_id: str, payload: YoutubeIngestRequest) -> ProjectOut:
    _require_project(project_id)
    # Validate before flipping status, so a bad URL never leaves the project stuck "ingesting".
    youtube_module.extract_video_id(payload.url)

    src_dir = storage.source_dir(project_id)
    src_dir.mkdir(parents=True, exist_ok=True)
    for existing in src_dir.iterdir():
        if existing.is_file():
            existing.unlink()

    db.update_project(project_id, status="ingesting")
    try:
        video_path, info = youtube_module.download(payload.url, src_dir)
        final_path = src_dir / f"source{video_path.suffix}"
        if video_path != final_path:
            video_path.rename(final_path)
        title = info.get("title") or payload.url
        return _finish_ingest(project_id, final_path, "youtube", title)
    except Exception:
        db.update_project(project_id, status="error", error_message="Failed to download that YouTube video.")
        raise


@router.get("/{project_id}/media")
def get_media(project_id: str) -> FileResponse:
    _require_project(project_id)
    source = storage.find_source_file(project_id)
    if source is None:
        raise NotFoundError(
            "No video has been added to this project yet.",
            suggestion="Upload a video or paste a YouTube URL first.",
        )
    return FileResponse(source, filename=source.name)
