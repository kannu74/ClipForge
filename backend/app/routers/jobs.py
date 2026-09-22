"""Background processing: start the full pipeline, re-pick clips, and poll
or cancel jobs."""
from __future__ import annotations

from fastapi import APIRouter

from app import db, jobs, pipeline, project_settings
from app.errors import NotFoundError, ValidationFailedError
from app.models import JobOut, ProcessRequest
from app import youtube as youtube_module
from app.routers.common import require_project

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post("/projects/{project_id}/process", response_model=JobOut)
def process(project_id: str, payload: ProcessRequest) -> JobOut:
    """Run the whole pipeline in the background: (download ->) transcribe ->
    find moments -> rank clips -> render (if auto-render is on)."""
    require_project(project_id)
    if payload.settings:
        try:
            project_settings.update(project_id, payload.settings)
        except Exception as exc:
            raise ValidationFailedError("Some of those settings aren't valid.", detail=str(exc))
    if payload.youtube_url:
        youtube_module.extract_video_id(payload.youtube_url)
        db.update_project(project_id, source_type="youtube", source_reference=payload.youtube_url, status="queued")
    else:
        pipeline.require_source(project_id)
    running = jobs.active_jobs(project_id, "process") + jobs.active_jobs(project_id, "rerank")
    if running:
        return JobOut(**running[0])
    job = jobs.enqueue(
        "process",
        project_id,
        {"youtube_url": payload.youtube_url, "force_transcribe": payload.force_transcribe},
    )
    return JobOut(**job)


@router.post("/projects/{project_id}/rerank", response_model=JobOut)
def rerank(project_id: str) -> JobOut:
    """Pick clips again with the current length/count settings, reusing the
    existing transcript (fast -- no re-transcription)."""
    require_project(project_id)
    from app import storage

    if not storage.transcript_path(project_id).exists():
        raise ValidationFailedError("This project hasn't been transcribed yet.", suggestion="Process the video first.")
    running = jobs.active_jobs(project_id, "process") + jobs.active_jobs(project_id, "rerank")
    if running:
        return JobOut(**running[0])
    return JobOut(**jobs.enqueue("rerank", project_id, {}))


@router.get("/projects/{project_id}/jobs", response_model=list[JobOut])
def project_jobs(project_id: str, limit: int = 30) -> list[JobOut]:
    require_project(project_id)
    return [JobOut(**j) for j in jobs.list_jobs(project_id, limit)]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str) -> JobOut:
    job = jobs.get_job(job_id)
    if job is None:
        raise NotFoundError("That job doesn't exist.")
    return JobOut(**job)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str) -> JobOut:
    job = jobs.request_cancel(job_id)
    if job is None:
        raise NotFoundError("That job doesn't exist.")
    return JobOut(**job)
