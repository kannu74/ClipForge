"""Video ingestion: local file upload and YouTube URL fetch, plus media
streaming (with Range support, so the preview player can seek) and single
frame grabs for the editor."""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import Response

from app import db, media, pipeline, storage
from app.errors import NotFoundError, ValidationFailedError
from app.http_utils import ranged_file_response
from app.logging_config import get_logger
from app.media import SUPPORTED_EXTENSIONS
from app.models import ProjectOut, YoutubeIngestRequest
from app import youtube as youtube_module
from app.routers.common import project_out, require_project

router = APIRouter(prefix="/api/projects", tags=["ingest"])
logger = get_logger("routers.ingest")


@router.post("/{project_id}/upload", response_model=ProjectOut)
def upload_video(project_id: str, file: UploadFile = File(...)) -> ProjectOut:
    # Plain `def`: FastAPI runs it in a worker thread, so copying a multi-GB
    # upload doesn't freeze every other request (progress polling etc.).
    require_project(project_id)

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValidationFailedError(
            f"'{suffix or 'that file'}' isn't a supported video format.",
            suggestion=f"Use one of: {', '.join(sorted(SUPPORTED_EXTENSIONS))}.",
        )

    src_dir = pipeline.clear_source_dir(project_id)
    dest = src_dir / f"source{suffix}"
    db.update_project(project_id, status="ingesting")
    try:
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out, length=4 * 1024 * 1024)
    except OSError as exc:
        dest.unlink(missing_ok=True)
        db.update_project(project_id, status="error", error_message="The upload couldn't be saved.")
        raise ValidationFailedError(
            "The upload couldn't be saved.",
            suggestion="Check there's enough free disk space, then try again.",
            detail=str(exc),
        ) from exc
    finally:
        file.file.close()

    try:
        pipeline.finish_ingest(project_id, dest, "local", file.filename or dest.name)
    except Exception:
        db.update_project(project_id, status="error", error_message="Failed to process the uploaded video.")
        raise
    return project_out(db.get_project(project_id))


@router.post("/{project_id}/youtube", response_model=ProjectOut)
def ingest_youtube(project_id: str, payload: YoutubeIngestRequest) -> ProjectOut:
    require_project(project_id)
    # Validate before touching anything, so a bad URL never leaves the project stuck "ingesting".
    youtube_module.extract_video_id(payload.url)
    pipeline.do_download(project_id, payload.url)
    return project_out(db.get_project(project_id))


@router.api_route("/{project_id}/media", methods=["GET", "HEAD"])
def get_media(project_id: str, request: Request) -> Response:
    require_project(project_id)
    source = storage.find_source_file(project_id)
    if source is None:
        raise NotFoundError(
            "No video has been added to this project yet.",
            suggestion="Upload a video or paste a YouTube URL first.",
        )
    preview = pipeline.preview_path(project_id)
    if preview.exists():
        return ranged_file_response(request, preview, media_type="video/mp4")
    return ranged_file_response(request, source)


@router.get("/{project_id}/frame")
def get_frame(project_id: str, request: Request, t: float = 0.0, w: int = 640) -> Response:
    require_project(project_id)
    source = pipeline.require_source(project_id)
    w = max(160, min(w, 1280))
    frames = storage.analysis_dir(project_id) / "frames"
    out = frames / f"{int(round(t * 10))}_{w}.jpg"
    if not out.exists():
        media.extract_frame(source, t, out, width=w)
    return ranged_file_response(request, out, media_type="image/jpeg")
