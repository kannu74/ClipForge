"""Clips: generate (rank), list, edit (trim / retitle / caption + framing
overrides / caption text), add manual clips, render, and download."""
from __future__ import annotations

import re
import zipfile

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app import clip_store, pipeline, social, storage
from app.errors import NotFoundError, ValidationFailedError
from app.http_utils import ranged_file_response
from app.logging_config import get_logger
from app.models import (
    CaptionWordsRequest,
    ClipBatchRequest,
    ClipCreateRequest,
    ClipExtendRequest,
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


@router.post("/{project_id}/clips/batch", response_model=list[ClipOut], status_code=201)
def create_clips_batch(project_id: str, payload: ClipBatchRequest) -> list[ClipOut]:
    """Add several hand-marked clips at once (Clip 1, Clip 2, ...). Every
    range is validated before any is added, so a bad one adds nothing."""
    row = require_project(project_id)
    pipeline.require_source(project_id)
    meta = pipeline.project_meta(project_id)
    ranges = [
        (*clip_store.validate_range(c.start, c.end, meta.get("duration_seconds")), c.title.strip() or f"Clip {i}")
        for i, c in enumerate(payload.clips, 1)
    ]
    made: list[dict] = []
    # add_manual_clip puts each new clip first, so add in reverse to keep Clip 1 on top.
    for start, end, title in reversed(ranges):
        made.append(clip_store.add_manual_clip(
            project_id, start, end, title, _excerpt(project_id, start, end), row["content_type"]))
    made.reverse()
    out = []
    for clip in made:
        if payload.render:
            pipeline.enqueue_render(project_id, clip["id"])
            clip = clip_store.get_clip(project_id, clip["id"])
        out.append(ClipOut(**clip))
    return out


def _range_patch(project_id: str, clip: dict, start: float, end: float) -> dict:
    """Fields to update when a clip's range changes to (start, end)."""
    if (start, end) == (clip["start"], clip["end"]):
        return {}
    patch: dict = {
        "start": start,
        "end": end,
        "edited": True,
        "transcript_excerpt": _excerpt(project_id, start, end) or clip["transcript_excerpt"],
        "duration_explanation": f"Trimmed by you to {end - start:.0f} seconds.",
    }
    if clip.get("caption_words"):
        # Keep the creator's edited words inside the new range, and fill any
        # newly-included stretch with transcript words so an extended clip
        # isn't left without captions.
        old_s, old_e = clip["start"], clip["end"]
        kept = [w for w in clip["caption_words"] if w["end"] > start and w["start"] < end]
        t = storage.read_json(storage.transcript_path(project_id)) or {"segments": []}
        fill = [
            {"word": w.word, "start": w.start, "end": w.end}
            for w in words_in_range(units_from_transcript(t), start, end)
            if (w.start + w.end) / 2 < old_s or (w.start + w.end) / 2 > old_e
        ]
        patch["caption_words"] = sorted(kept + fill, key=lambda w: w["start"]) or None
    return patch


def _snap_to_speech(project_id: str, start: float, end: float, moved_start: bool, moved_end: bool) -> tuple[float, float]:
    """After extending, never cut through a word: a moved edge that lands
    inside a word is pulled to the edge of that word."""
    t = storage.read_json(storage.transcript_path(project_id)) or {"segments": []}
    for u in units_from_transcript(t):
        if u.end < start - 1 or u.start > end + 1:
            continue
        for w in u.words:
            if moved_start and w.start < start < w.end:
                start = max(0.0, w.start - 0.05)
            if moved_end and w.start < end < w.end:
                end = w.end + 0.1
    return start, end


@router.post("/{project_id}/clips/{clip_id}/extend", response_model=ClipOut)
def extend_clip(project_id: str, clip_id: str, payload: ClipExtendRequest) -> ClipOut:
    """Grow a clip on the spot: pull in more footage before and/or after it."""
    require_project(project_id)
    pipeline.require_source(project_id)
    clip = clip_store.get_clip(project_id, clip_id)
    meta = pipeline.project_meta(project_id)
    media_duration = meta.get("duration_seconds")
    start = max(0.0, clip["start"] - payload.before)
    end = clip["end"] + payload.after
    if media_duration:
        end = min(end, float(media_duration))
    start, end = _snap_to_speech(project_id, start, end, payload.before > 0, payload.after > 0)
    if media_duration:
        end = min(end, float(media_duration))
    start, end = clip_store.validate_range(start, end, media_duration)
    if (start, end) == (clip["start"], clip["end"]):
        raise ValidationFailedError(
            "There's no more footage to add in that direction.",
            suggestion="The clip already reaches the start or end of the video.",
        )
    patch = _range_patch(project_id, clip, start, end)
    patch["duration_explanation"] = (
        f"Extended by you to {end - start:.0f} seconds "
        f"({clip['start'] - start:+.0f}s before, {end - clip['end']:+.0f}s after)."
    )
    clip_store.update_clip(project_id, clip_id, patch)
    if payload.render:
        pipeline.enqueue_render(project_id, clip_id)
    return ClipOut(**clip_store.get_clip(project_id, clip_id))


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
        patch.update(_range_patch(project_id, clip, start, end))
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


@router.get("/{project_id}/clips/{clip_id}/social")
def clip_social(project_id: str, clip_id: str, ai: bool = False) -> dict:
    """Caption + hashtag suggestions for posting this clip. `ai=true` asks the
    local Ollama model (slower); the default is instant and rule-based."""
    row = require_project(project_id)
    clip = clip_store.get_clip(project_id, clip_id)
    fn = social.suggest_with_llm if ai else social.suggest
    return fn(clip.get("transcript_excerpt", ""), clip.get("title", ""), clip.get("category", ""), row["content_type"])


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
    from app import jobs

    active = {j["params"].get("clip_id") for j in jobs.active_jobs(project_id, "render")}
    out = []
    for c in payload["clips"]:
        r = c.get("render") or {}
        if c["id"] in active:
            continue
        # "queued"/"rendering" with no live job means it was interrupted.
        if only_missing and r.get("status") == "done" and not r.get("stale"):
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
    import uuid

    from starlette.background import BackgroundTask

    rdir = storage.renders_dir(project_id)
    for old in rdir.glob("_zip_*.zip"):  # leftovers from interrupted downloads
        try:
            old.unlink()
        except OSError:
            pass
    zip_path = rdir / f"_zip_{uuid.uuid4().hex[:8]}.zip"
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
    resp = ranged_file_response(request, zip_path, media_type="application/zip", download_name=zip_name)

    def _cleanup() -> None:
        try:
            zip_path.unlink()
        except OSError:
            pass  # Windows may still hold it; removed on the next download

    resp.background = BackgroundTask(_cleanup)
    return resp


@router.post("/{project_id}/clips/refresh-excerpts", response_model=ClipsOut)
def refresh_excerpts(project_id: str) -> ClipsOut:
    """Recompute each clip's transcript excerpt (after transcript edits)."""
    require_project(project_id)

    def fn(payload: dict) -> None:
        for c in payload["clips"]:
            c["transcript_excerpt"] = _excerpt(project_id, c["start"], c["end"]) or c["transcript_excerpt"]

    clip_store.mutate(project_id, fn)
    return get_clips(project_id)

