"""Clips: generate (rank), list, edit (trim / retitle / caption + framing
overrides / caption text), add manual clips, render, and download."""
from __future__ import annotations

import re
import zipfile

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app import clip_store, pipeline, storage
from app.errors import NotFoundError, ValidationFailedError
from app.http_utils import ranged_file_response
from app.logging_config import get_logger
from app.models import (
    CaptionWordsRequest,
    ClipCreateRequest,
    ClipOut,
    ClipPatchRequest,
    ClipsOut,
    GenerateClipsRequest,
    JobOut,
)
from app.project_settings import CaptionSettings, ReframeSettings
from app.render import caption_words_for_clip
from app.routers.common import require_project
from app.units import units_from_transcript, words_in_range

router = APIRouter(prefix="/api/projects", tags=["clips"])
logger = get_logger("routers.clips")


def _clips_out(project_id: str, payload: dict) -> ClipsOut:
    payload = clip_store.with_staleness(project_id, payload)
    return ClipsOut(**payload)


@router.post("/{project_id}/generate-clips", response_model=ClipsOut)
def generate_clips(project_id: str, payload: GenerateClipsRequest) -> ClipsOut:
    require_project(project_id)
    result = pipeline.do_rank(
        project_id,
        count=payload.count,
        preset_name=payload.duration_preset,
        custom_min=payload.custom_min_seconds,
        custom_max=payload.custom_max_seconds,
        custom_preferred=payload.custom_preferred_seconds,
    )
    return _clips_out(project_id, result)


@router.get("/{project_id}/clips", response_model=ClipsOut)
def get_clips(project_id: str) -> ClipsOut:
    require_project(project_id)
    payload = clip_store.load(project_id)
    if payload is None:
        raise NotFoundError("No clips generated yet.", suggestion="Generate clips first.")
    return _clips_out(project_id, payload)


def _excerpt(project_id: str, start: float, end: float) -> str:
    t = storage.read_json(storage.transcript_path(project_id)) or {"segments": []}
    words = words_in_range(units_from_transcript(t), start, end)
    return " ".join(w.word for w in words)


@router.post("/{project_id}/clips", response_model=ClipOut, status_code=201)
def create_clip(project_id: str, payload: ClipCreateRequest) -> ClipOut:
    row = require_project(project_id)
    pipeline.require_source(project_id)
    meta = pipeline.project_meta(project_id)
    start, end = clip_store.validate_range(payload.start, payload.end, meta.get("duration_seconds"))
    clip = clip_store.add_manual_clip(
        project_id, start, end, payload.title.strip(), _excerpt(project_id, start, end), row["content_type"]
    )
    if payload.render:
        pipeline.enqueue_render(project_id, clip["id"])
        clip = clip_store.get_clip(project_id, clip["id"])
    return ClipOut(**clip)


@router.patch("/{project_id}/clips/{clip_id}", response_model=ClipOut)
def patch_clip(project_id: str, clip_id: str, payload: ClipPatchRequest) -> ClipOut:
    require_project(project_id)
    clip = clip_store.get_clip(project_id, clip_id)
    patch: dict = {}
    if payload.start is not None or payload.end is not None:
        meta = pipeline.project_meta(project_id)
        start = payload.start if payload.start is not None else clip["start"]
        end = payload.end if payload.end is not None else clip["end"]
        start, end = clip_store.validate_range(start, end, meta.get("duration_seconds"))
        if (start, end) != (clip["start"], clip["end"]):
            patch.update({"start": start, "end": end, "edited": True})
            patch["transcript_excerpt"] = _excerpt(project_id, start, end) or clip["transcript_excerpt"]
            patch["duration_explanation"] = f"Trimmed by you to {end - start:.0f} seconds."
            if clip.get("caption_words"):
                # Keep edited caption text, but drop words now outside the clip.
                patch["caption_words"] = [
                    w for w in clip["caption_words"] if w["end"] > start and w["start"] < end
                ] or None
    if payload.title is not None:
        patch["title"] = payload.title.strip()
    if payload.clear_caption_overrides:
        patch["caption_overrides"] = None
    elif payload.caption_overrides:
        merged = {**(clip.get("caption_overrides") or {}), **payload.caption_overrides}
        try:
            CaptionSettings(**{**CaptionSettings().model_dump(), **merged})
        except Exception as exc:
            raise ValidationFailedError("Those caption settings aren't valid.", detail=str(exc))
        patch["caption_overrides"] = payload.caption_overrides
    if payload.clear_reframe_overrides:
        patch["reframe_overrides"] = None
    elif payload.reframe_overrides:
        merged = {**(clip.get("reframe_overrides") or {}), **payload.reframe_overrides}
        try:
            ReframeSettings(**{**ReframeSettings().model_dump(), **merged})
        except Exception as exc:
            raise ValidationFailedError("Those framing settings aren't valid.", detail=str(exc))
        patch["reframe_overrides"] = payload.reframe_overrides
    if patch:
        clip = clip_store.update_clip(project_id, clip_id, patch)
    if payload.render:
        pipeline.enqueue_render(project_id, clip_id)
        clip = clip_store.get_clip(project_id, clip_id)
    return ClipOut(**clip)


@router.delete("/{project_id}/clips/{clip_id}", status_code=204, response_model=None)
def delete_clip(project_id: str, clip_id: str) -> None:
    require_project(project_id)
    from app import jobs

    for j in jobs.active_jobs(project_id, "render"):
        if j["params"].get("clip_id") == clip_id:
            jobs.request_cancel(j["id"])
    clip_store.delete_clip(project_id, clip_id)
    return None


@router.get("/{project_id}/clips/{clip_id}/words")
def get_caption_words(project_id: str, clip_id: str) -> dict:
    require_project(project_id)
    clip = clip_store.get_clip(project_id, clip_id)
    t = storage.read_json(storage.transcript_path(project_id)) or {"segments": []}
    words = caption_words_for_clip(clip, units_from_transcript(t))
    out = [
        {"word": (w["word"] if isinstance(w, dict) else w.word),
         "start": round(float(w["start"] if isinstance(w, dict) else w.start), 3),
         "end": round(float(w["end"] if isinstance(w, dict) else w.end), 3)}
        for w in words
    ]
    return {"clip_id": clip_id, "edited": bool(clip.get("caption_words")), "words": out}


@router.put("/{project_id}/clips/{clip_id}/words")
def put_caption_words(project_id: str, clip_id: str, payload: CaptionWordsRequest) -> dict:
    require_project(project_id)
    clip_store.get_clip(project_id, clip_id)
    words = None
    if payload.words is not None:
        words = [
            {"word": w.word.strip(), "start": w.start, "end": max(w.end, w.start + 0.05)}
            for w in payload.words
            if w.word.strip()
        ]
        words.sort(key=lambda w: w["start"])
    clip_store.update_clip(project_id, clip_id, {"caption_words": words or None, "edited": True})
    if payload.render:
        pipeline.enqueue_render(project_id, clip_id)
    return get_caption_words(project_id, clip_id)


@router.post("/{project_id}/clips/{clip_id}/render", response_model=JobOut)
def render_clip(project_id: str, clip_id: str) -> JobOut:
    require_project(project_id)
    pipeline.require_source(project_id)
    clip_store.get_clip(project_id, clip_id)
    return JobOut(**pipeline.enqueue_render(project_id, clip_id))


@router.post("/{project_id}/render-all", response_model=list[JobOut])
def render_all(project_id: str, only_missing: bool = True) -> list[JobOut]:
    require_project(project_id)
    pipeline.require_source(project_id)
    payload = clip_store.load(project_id)
    if payload is None:
        raise NotFoundError("No clips yet.", suggestion="Process the video first.")
    payload = clip_store.with_staleness(project_id, payload)
    out = []
    for c in payload["clips"]:
        r = c.get("render") or {}
        if only_missing and r.get("status") == "done" and not r.get("stale"):
            continue
        if r.get("status") in ("queued", "rendering"):
            continue
        out.append(JobOut(**pipeline.enqueue_render(project_id, c["id"])))
    return out


def _safe_name(title: str, fallback: str) -> str:
    name = re.sub(r"[^\w\s\-ऀ-ॿ]", "", title or "").strip()
    name = re.sub(r"\s+", " ", name)[:60].strip()
    return name or fallback


def _render_file(project_id: str, clip_id: str, key: str):
    clip = clip_store.get_clip(project_id, clip_id)
    r = clip.get("render") or {}
    name = r.get(key)
    if r.get("status") != "done" or not name:
        raise NotFoundError("This clip hasn't been rendered yet.", suggestion="Render it first.")
    path = storage.renders_dir(project_id) / name
    if not path.exists():
        raise NotFoundError("The rendered file is missing.", suggestion="Render the clip again.")
    return clip, path


@router.api_route("/{project_id}/clips/{clip_id}/video", methods=["GET", "HEAD"])
def clip_video(project_id: str, clip_id: str, request: Request, download: bool = False) -> Response:
    require_project(project_id)
    clip, path = _render_file(project_id, clip_id, "file")
    name = _safe_name(clip.get("title", ""), f"clip-{clip_id}") + ".mp4" if download else None
    return ranged_file_response(request, path, media_type="video/mp4", download_name=name)


@router.get("/{project_id}/clips/{clip_id}/thumbnail")
def clip_thumbnail(project_id: str, clip_id: str, request: Request) -> Response:
    require_project(project_id)
    _clip, path = _render_file(project_id, clip_id, "thumbnail")
    return ranged_file_response(request, path, media_type="image/jpeg")


@router.get("/{project_id}/clips/{clip_id}/srt")
def clip_srt(project_id: str, clip_id: str, request: Request) -> Response:
    require_project(project_id)
    clip, path = _render_file(project_id, clip_id, "srt")
    name = _safe_name(clip.get("title", ""), f"clip-{clip_id}") + ".srt"
    return ranged_file_response(request, path, media_type="application/x-subrip", download_name=name)


@router.get("/{project_id}/clips.zip")
def clips_zip(project_id: str, request: Request) -> Response:
    row = require_project(project_id)
    payload = clip_store.load(project_id)
    if payload is None:
        raise NotFoundError("No clips yet.", suggestion="Process the video first.")
    rdir = storage.renders_dir(project_id)
    zip_path = rdir / "_all_clips.zip"
    used: set[str] = set()
    n = 0
    # Written to disk (not memory): ten 1080p clips can be several hundred MB.
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for i, c in enumerate(payload["clips"], start=1):
            r = c.get("render") or {}
            if r.get("status") != "done" or not r.get("file"):
                continue
            mp4 = rdir / r["file"]
            if not mp4.exists():
                continue
            base = f"{i:02d} - " + _safe_name(c.get("title", ""), c["id"])
            while base in used:
                base += "_"
            used.add(base)
            zf.write(mp4, base + ".mp4")
            if r.get("srt") and (rdir / r["srt"]).exists():
                zf.write(rdir / r["srt"], base + ".srt")
            n += 1
    if n == 0:
        zip_path.unlink(missing_ok=True)
        raise NotFoundError("No rendered clips to download yet.", suggestion="Render your clips first.")
    zip_name = _safe_name(row["name"], "clips") + " - clips.zip"
    return ranged_file_response(request, zip_path, media_type="application/zip", download_name=zip_name)


@router.post("/{project_id}/clips/refresh-excerpts", response_model=ClipsOut)
def refresh_excerpts(project_id: str) -> ClipsOut:
    """Recompute each clip's transcript excerpt (after transcript edits)."""
    require_project(project_id)

    def fn(payload: dict) -> None:
        for c in payload["clips"]:
            c["transcript_excerpt"] = _excerpt(project_id, c["start"], c["end"]) or c["transcript_excerpt"]

    clip_store.mutate(project_id, fn)
    return get_clips(project_id)

