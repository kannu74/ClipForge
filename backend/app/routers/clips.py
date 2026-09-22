"""Phase 4/5 endpoints: rank Phase 3's candidate moments into a final,
diversified, boundary-refined clip selection."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import APIRouter

from app import db, storage
from app.audio_analysis import compute_energy_profile
from app.duration_presets import DurationPreset, resolve_bounds
from app.errors import NotFoundError, ValidationFailedError
from app.logging_config import get_logger
from app.media import extract_audio
from app.models import ClipOut, ClipsOut, GenerateClipsRequest
from app.moments import Moment
from app.ranking import select_clips

router = APIRouter(prefix="/api/projects", tags=["clips"])
logger = get_logger("routers.clips")


def _require_project(project_id: str):
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("That project doesn't exist.", suggestion="It may have been deleted.")
    return row


@router.post("/{project_id}/generate-clips", response_model=ClipsOut)
def generate_clips(project_id: str, payload: GenerateClipsRequest) -> ClipsOut:
    row = _require_project(project_id)

    transcript = storage.read_json(storage.transcript_path(project_id))
    if transcript is None:
        raise ValidationFailedError(
            "This project doesn't have a transcript yet.",
            suggestion="Transcribe the video before generating clips.",
        )
    moments_payload = storage.read_json(storage.moments_path(project_id))
    if moments_payload is None:
        raise ValidationFailedError(
            "No candidate moments have been detected yet.",
            suggestion="Run moment detection before generating clips.",
        )
    source = storage.find_source_file(project_id)
    if source is None:
        raise ValidationFailedError("This project doesn't have a video yet.")

    try:
        preset = DurationPreset(payload.duration_preset)
    except ValueError:
        raise ValidationFailedError(
            f"'{payload.duration_preset}' isn't a valid duration preset.",
            suggestion="Use one of: ultra_short, short, standard, extended, custom.",
        )
    try:
        bounds = resolve_bounds(
            preset,
            custom_min=payload.custom_min_seconds,
            custom_max=payload.custom_max_seconds,
            custom_preferred=payload.custom_preferred_seconds,
        )
    except ValueError as exc:
        raise ValidationFailedError(str(exc), suggestion="Provide custom_min_seconds and custom_max_seconds.")

    segments = [
        SimpleNamespace(start=s["start"], end=s["end"], text=s["text"]) for s in transcript["segments"]
    ]
    moments = [
        Moment(
            id=m["id"],
            start=m["start"],
            end=m["end"],
            category=m["category"],
            score=m["score"],
            signals=m["signals"],
            transcript_excerpt=m["transcript_excerpt"],
            reason=m["reason"],
            start_idx=m["start_idx"],
            end_idx=m["end_idx"],
            llm_enriched=m["llm_enriched"],
        )
        for m in moments_payload["moments"]
    ]

    audio_scratch = storage.project_dir(project_id) / "clips" / "_audio.wav"
    try:
        extract_audio(source, audio_scratch)
        energy_profile = compute_energy_profile(audio_scratch)
        result = select_clips(moments, segments, energy_profile, bounds, payload.count)
    finally:
        audio_scratch.unlink(missing_ok=True)

    created_at = datetime.now(timezone.utc).isoformat()
    clip_dicts = [
        {
            "id": c.id,
            "start": c.start,
            "end": c.end,
            "category": c.category,
            "total_score": c.total_score,
            "sub_scores": c.sub_scores,
            "transcript_excerpt": c.transcript_excerpt,
            "reason": c.reason,
            "duration_explanation": c.duration_explanation,
            "llm_enriched": c.llm_enriched,
        }
        for c in result.clips
    ]
    response_payload = {
        "project_id": project_id,
        "content_type": row["content_type"],
        "duration_preset": preset.value,
        "requested_count": result.requested_count,
        "considered_count": result.considered_count,
        "message": result.message,
        "clips": clip_dicts,
        "created_at": created_at,
    }
    storage.write_json(storage.clips_path(project_id), response_payload)
    logger.info(
        "Generated %d/%d clips for project %s (considered %d candidates)",
        len(result.clips), payload.count, project_id, result.considered_count,
    )
    return ClipsOut(**response_payload)


@router.get("/{project_id}/clips", response_model=ClipsOut)
def get_clips(project_id: str) -> ClipsOut:
    _require_project(project_id)
    payload = storage.read_json(storage.clips_path(project_id))
    if payload is None:
        raise NotFoundError("No clips generated yet.", suggestion="Generate clips first.")
    return ClipsOut(**payload)
