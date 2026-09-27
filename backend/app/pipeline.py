"""
The end-to-end pipeline as reusable steps, shared by the HTTP endpoints
(synchronous, used by tests and power users) and the background jobs the UI
uses. Each step caches its output on disk and is skipped when that output is
still valid, so re-running after a failure resumes instead of starting over:

  download  -> source/source.mp4            (YouTube only)
  transcribe-> transcript/transcript.json   (keyed by range + model)
  energy    -> analysis/energy.json
  detect    -> moments/moments.json
  rank      -> clips/clips.json             (manual clips are preserved)
  render    -> renders/<clip>.mp4 (+ .jpg thumbnail, .srt, QC report)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app import clip_store, db, jobs, media, project_settings, render, storage
from app import transcription as transcription_module
from app import youtube as youtube_module
from app.audio_analysis import EnergyProfile, compute_energy_profile, load_profile, save_profile
from app.duration_presets import DurationPreset, resolve_bounds
from app.errors import NotFoundError, ValidationFailedError
from app.logging_config import get_logger
from app.moments import detect_moments, moment_from_dict, moment_to_dict
from app.ranking import select_clips
from app.titles import llm_title
from app.units import units_from_transcript

logger = get_logger("pipeline")
ProgressFn = Callable[[float, str], None]


def _noop(frac: float, msg: str = "") -> None:
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_project(project_id: str):
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("That project doesn't exist.", suggestion="It may have been deleted.")
    return row


def require_source(project_id: str) -> Path:
    source = storage.find_source_file(project_id)
    if source is None:
        raise ValidationFailedError(
            "This project doesn't have a video yet.",
            suggestion="Upload a video or paste a YouTube URL first.",
        )
    return source


def project_meta(project_id: str) -> dict:
    row = require_project(project_id)
    try:
        return json.loads(row["metadata_json"] or "{}")
    except (TypeError, ValueError):
        return {}


def finish_ingest(project_id: str, video_path: Path, source_type: str, source_reference: str) -> None:
    metadata = media.probe(video_path)
    db.update_project(
        project_id,
        source_type=source_type,
        source_reference=source_reference,
        status="ready",
        metadata_json=json.dumps(metadata.to_dict()),
        error_message=None,
    )
    manifest = storage.read_manifest(project_id) or {}
    manifest.update({"source_type": source_type, "source_reference": source_reference, "metadata": metadata.to_dict()})
    storage.write_manifest(project_id, manifest)
    # A new source invalidates everything derived from the old one.
    for p in (
        storage.transcript_path(project_id),
        storage.moments_path(project_id),
        storage.clips_path(project_id),
        storage.energy_path(project_id),
        storage.analysis_dir(project_id) / "preview.mp4",
    ):
        p.unlink(missing_ok=True)
    frames = storage.analysis_dir(project_id) / "frames"
    if frames.exists():
        for f in frames.iterdir():
            f.unlink(missing_ok=True)
    logger.info("Ingested source for project %s (%s, %.1fs)", project_id, source_type, metadata.duration_seconds)


def clear_source_dir(project_id: str) -> Path:
    src_dir = storage.source_dir(project_id)
    src_dir.mkdir(parents=True, exist_ok=True)
    for existing in src_dir.iterdir():
        if existing.is_file():
            existing.unlink()
    return src_dir


def do_download(
    project_id: str,
    url: str,
    progress: ProgressFn = _noop,
    section: tuple[float, float | None] | None = None,
) -> Path:
    youtube_module.extract_video_id(url)
    src_dir = clear_source_dir(project_id)
    db.update_project(project_id, status="ingesting", source_type="youtube", source_reference=url)
    try:
        video_path, info = youtube_module.download(url, src_dir, on_progress=progress, section=section)
        final_path = src_dir / f"source{video_path.suffix}"
        if video_path != final_path:
            video_path.replace(final_path)
        title = info.get("title") or url
        finish_ingest(project_id, final_path, "youtube", title)
        row = db.get_project(project_id)
        if row is not None and (row["name"] or "").startswith("YouTube video") and info.get("title"):
            db.update_project(project_id, name=str(info["title"])[:200])
        return final_path
    except Exception:
        db.update_project(project_id, status="error", error_message="Couldn't download that YouTube video.")
        raise


def _transcript_is_current(project_id: str, ps: project_settings.ProjectSettings) -> bool:
    t = storage.read_json(storage.transcript_path(project_id))
    if t is None:
        return False
    return t.get("range_start") == ps.range_start and t.get("range_end") == ps.range_end


def do_transcribe(
    project_id: str,
    progress: ProgressFn = _noop,
    model_size: str | None = None,
    force: bool = False,
    engine=None,
) -> dict:
    require_project(project_id)
    source = require_source(project_id)
    ps = project_settings.load(project_id)
    if not force and model_size is None and _transcript_is_current(project_id, ps):
        progress(1.0, "Transcript already up to date.")
        return storage.read_json(storage.transcript_path(project_id))  # type: ignore[return-value]

    meta = project_meta(project_id)
    duration = float(meta.get("duration_seconds") or 0) or None
    start = ps.range_start if ps.range_start else None
    end = ps.range_end if ps.range_end and (duration is None or ps.range_end < duration) else None
    if start is not None and end is not None and end - start < 5:
        raise ValidationFailedError(
            "The selected part of the video is too short.", suggestion="Pick a range of at least a few seconds."
        )

    db.update_project(project_id, status="transcribing", error_message=None)
    audio_scratch = storage.project_dir(project_id) / "transcript" / "_audio.wav"
    try:
        result = transcription_module.run_transcription(
            source,
            audio_scratch,
            model_size=model_size or ps.whisper_model,
            engine=engine or transcription_module.FasterWhisperEngine(),
            start=start,
            end=end,
            language=ps.language or None,
            on_progress=progress,
        )
    except Exception:
        db.update_project(project_id, status="error", error_message="Transcription failed.")
        raise

    payload = transcription_module.to_dict(project_id, result, _now(), ps.range_start, ps.range_end)
    storage.write_json(storage.transcript_path(project_id), payload)
    # Downstream results are now stale.
    storage.moments_path(project_id).unlink(missing_ok=True)
    db.update_project(project_id, status="ready")
    logger.info("Transcript ready for project %s (%d segments)", project_id, len(payload["segments"]))
    return payload


def ensure_energy(project_id: str, progress: ProgressFn = _noop) -> EnergyProfile:
    cached = load_profile(storage.energy_path(project_id))
    if cached is not None:
        return cached
    source = require_source(project_id)
    progress(0.0, "Analyzing audio energy...")
    profile = compute_energy_profile(source)
    save_profile(profile, storage.energy_path(project_id))
    return profile


def _load_transcript(project_id: str) -> dict:
    transcript = storage.read_json(storage.transcript_path(project_id))
    if transcript is None:
        raise ValidationFailedError(
            "This project doesn't have a transcript yet.",
            suggestion="Transcribe the video first.",
        )
    return transcript


def do_detect(project_id: str, progress: ProgressFn = _noop, min_candidates: int = 0, ollama_client=None) -> dict:
    row = require_project(project_id)
    transcript = _load_transcript(project_id)
    require_source(project_id)
    units = units_from_transcript(transcript)
    db.update_project(project_id, status="analyzing")
    try:
        energy = ensure_energy(project_id, progress)
        progress(0.5, "Finding the best moments...")
        moments, ollama_used = detect_moments(
            row["content_type"], units, energy, ollama_client=ollama_client, min_candidates=min_candidates
        )
    except Exception:
        db.update_project(project_id, status="error", error_message="Moment detection failed.")
        raise
    payload = {
        "project_id": project_id,
        "content_type": row["content_type"],
        "moments": [moment_to_dict(m) for m in moments],
        "ollama_used": ollama_used,
        "created_at": _now(),
        "unit_count": len(units),
    }
    storage.write_json(storage.moments_path(project_id), payload)
    db.update_project(project_id, status="ready")
    logger.info("Detected %d candidate moments for project %s (ollama_used=%s)", len(moments), project_id, ollama_used)
    return payload


def do_rank(
    project_id: str,
    count: int | None = None,
    preset_name: str | None = None,
    custom_min: float | None = None,
    custom_max: float | None = None,
    custom_preferred: float | None = None,
    allow_low_confidence: bool | None = None,
    progress: ProgressFn = _noop,
) -> dict:
    row = require_project(project_id)
    ps = project_settings.load(project_id)
    transcript = _load_transcript(project_id)
    moments_payload = storage.read_json(storage.moments_path(project_id))
    if moments_payload is None:
        raise ValidationFailedError(
            "No candidate moments have been detected yet.",
            suggestion="Run moment detection before generating clips.",
        )
    require_source(project_id)
    count = count or ps.clip_count
    preset_name = preset_name or ps.duration_preset
    try:
        preset = DurationPreset(preset_name)
    except ValueError:
        raise ValidationFailedError(
            f"'{preset_name}' isn't a valid duration preset.",
            suggestion="Use one of: ultra_short, short, standard, extended, custom.",
        )
    try:
        bounds = resolve_bounds(
            preset,
            custom_min=custom_min if custom_min is not None else ps.custom_min_seconds,
            custom_max=custom_max if custom_max is not None else ps.custom_max_seconds,
            custom_preferred=custom_preferred,
        )
    except ValueError as exc:
        raise ValidationFailedError(str(exc), suggestion="Provide a custom minimum and maximum length.")

    units = units_from_transcript(transcript)
    moments = [moment_from_dict(m) for m in moments_payload["moments"]]
    energy = ensure_energy(project_id)
    meta = project_meta(project_id)
    media_end = float(meta.get("duration_seconds") or 0) or None
    progress(0.3, "Ranking and trimming clips...")
    result = select_clips(
        moments,
        units,
        energy,
        bounds,
        count,
        allow_low_confidence=ps.include_backup_clips if allow_low_confidence is None else allow_low_confidence,
        media_start=0.0,
        media_end=media_end,
    )

    ollama_ok = bool(moments_payload.get("ollama_used"))
    clip_dicts = []
    for c in result.clips:
        title = c.title
        if ollama_ok:
            title = llm_title(c.transcript_excerpt, row["content_type"], title)
        clip_dicts.append(
            clip_store.normalize_clip(
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
                    "virality": c.virality,
                    "confidence": c.confidence,
                    "title": title,
                    "origin": "auto",
                }
            )
        )

    old = clip_store.load(project_id)
    manual = [c for c in (old or {}).get("clips", []) if c.get("origin") == "manual"]
    payload = {
        "project_id": project_id,
        "content_type": row["content_type"],
        "duration_preset": preset.value,
        "requested_count": result.requested_count,
        "considered_count": result.considered_count,
        "message": result.message,
        "clips": manual + clip_dicts,
        "created_at": _now(),
    }
    clip_store.save(project_id, payload)
    # Old renders of auto clips are obsolete now.
    keep = {c["id"] for c in manual}
    rdir = storage.renders_dir(project_id)
    for p in rdir.iterdir():
        clip_id = p.name.split(".")[0]
        if clip_id not in keep and p.is_file():
            try:
                p.unlink()
            except OSError:
                pass
    logger.info(
        "Generated %d/%d clips for project %s (considered %d candidates)",
        len(result.clips), count, project_id, result.considered_count,
    )
    return payload


def do_render(project_id: str, clip_id: str, progress: ProgressFn = _noop) -> dict:
    require_project(project_id)
    source = require_source(project_id)
    ps = project_settings.load(project_id)
    clip = clip_store.get_clip(project_id, clip_id)
    transcript = storage.read_json(storage.transcript_path(project_id)) or {"segments": []}
    units = units_from_transcript(transcript)
    cap_cfg, ref_cfg = clip_store.effective_settings(ps, clip)
    rhash = clip_store.render_hash(ps, clip, int(transcript.get("revision") or 0))
    clip_store.update_clip(project_id, clip_id, {"render": {**clip.get("render", {}), "status": "rendering"}})
    try:
        info = render.render_clip(
            project_id, clip, units, cap_cfg, ref_cfg, ps.render, source, project_meta(project_id), progress
        )
    except jobs.JobCancelled:
        _reset_clip_render(project_id, clip_id)
        raise
    except Exception as exc:
        from app.errors import ClipForgeError

        from app import buildinfo

        msg = exc.message if isinstance(exc, ClipForgeError) else "Rendering failed."
        failed = {"status": "failed", "error": msg, "build": buildinfo.RUNNING}
        if isinstance(exc, ClipForgeError) and exc.suggestion:
            failed["suggestion"] = exc.suggestion
        clip_store.update_clip(project_id, clip_id, {"render": failed})
        raise
    info["hash"] = rhash
    clip_store.update_clip(project_id, clip_id, {"render": info})
    return info


# --- browser preview proxy ---

BROWSER_VIDEO_CODECS = {"h264", "vp8", "vp9", "av1"}
BROWSER_AUDIO_CODECS = {None, "aac", "mp3", "opus", "vorbis"}
BROWSER_CONTAINERS = {".mp4", ".m4v", ".webm", ".mov"}


def preview_path(project_id: str) -> Path:
    return storage.analysis_dir(project_id) / "preview.mp4"


def needs_preview(project_id: str) -> bool:
    src = storage.find_source_file(project_id)
    if src is None:
        return False
    meta = project_meta(project_id)
    return not (
        src.suffix.lower() in BROWSER_CONTAINERS
        and meta.get("video_codec") in BROWSER_VIDEO_CODECS
        and meta.get("audio_codec") in BROWSER_AUDIO_CODECS
    )


def ensure_preview(project_id: str, progress: ProgressFn = _noop) -> Path | None:
    if not needs_preview(project_id):
        return None
    out = preview_path(project_id)
    if out.exists():
        return out
    src = require_source(project_id)
    meta = project_meta(project_id)
    duration = float(meta.get("duration_seconds") or 1.0)
    tmp = out.with_name("preview.tmp.mp4")
    if meta.get("video_codec") == "h264" and meta.get("audio_codec") in ("aac", "mp3", None):
        args = ["-y", "-i", str(src.resolve()), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart", tmp.name]
        label = "Preparing browser preview"
    else:
        args = [
            "-y", "-i", str(src.resolve()), "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", "scale=-2:'min(720,ih)'", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", tmp.name,
        ]
        label = "Converting a preview copy for the browser"
    code, err = render._run_with_progress(args, duration, out.parent, progress, label)
    if code != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        logger.warning("Preview conversion failed: %s", err[-800:])
        return None
    tmp.replace(out)
    return out


# --- background jobs ---

def _reset_clip_render(project_id: str, clip_id: str) -> None:
    try:
        clip = clip_store.get_clip(project_id, clip_id)
    except Exception:
        return
    if (clip.get("render") or {}).get("status") in ("queued", "rendering"):
        # Keep an earlier finished render if the files are still there.
        prev = clip.get("render") or {}
        if prev.get("file") and (storage.renders_dir(project_id) / prev["file"]).exists():
            clip_store.update_clip(project_id, clip_id, {"render": {**prev, "status": "done"}})
        else:
            clip_store.update_clip(project_id, clip_id, {"render": {"status": "none"}})


@jobs.on_cancel_queued("render")
def _render_cancelled_before_start(job: dict) -> None:
    if job.get("project_id") and job["params"].get("clip_id"):
        _reset_clip_render(job["project_id"], job["params"]["clip_id"])


def recover_interrupted(stale_jobs: list[dict]) -> None:
    """After a restart: jobs that were queued/running are gone, so undo the
    'queued'/'rendering'/'processing' badges they left on clips and projects."""
    for j in stale_jobs:
        pid = j.get("project_id")
        if not pid or db.get_project(pid) is None:
            continue
        try:
            if j["kind"] == "render" and j["params"].get("clip_id"):
                _reset_clip_render(pid, j["params"]["clip_id"])
                # Renders are cheap to redo and the user asked for them: pick
                # them back up instead of leaving the clip un-rendered.
                if storage.find_source_file(pid) is not None:
                    enqueue_render(pid, j["params"]["clip_id"])
            elif j["kind"] in ("process", "rerank"):
                has_source = storage.find_source_file(pid) is not None
                db.update_project(
                    pid,
                    status="ready" if has_source else "error",
                    error_message=None if has_source else "Interrupted before the video finished downloading.",
                )
        except Exception:  # pragma: no cover - best effort
            logger.exception("Couldn't reset state for interrupted job %s", j.get("id"))


def retry_renders_after_update() -> int:
    """Re-queue renders that failed under a different (older) version of the
    code. When a render bug is fixed, the creator's failed clips are rendered
    again automatically on the next start -- once per version, so a clip that
    fails for another reason doesn't loop."""
    from app import buildinfo

    queued = 0
    for row in db.list_projects():
        pid = row["id"]
        try:
            payload = clip_store.load(pid)
            if not payload or storage.find_source_file(pid) is None:
                continue
            active = {j["params"].get("clip_id") for j in jobs.active_jobs(pid, "render")}
            for c in payload.get("clips", []):
                r = c.get("render") or {}
                if r.get("status") == "failed" and r.get("build") != buildinfo.RUNNING and c["id"] not in active:
                    enqueue_render(pid, c["id"])
                    queued += 1
        except Exception:  # pragma: no cover - best effort
            logger.exception("Couldn't re-queue failed renders for project %s", pid)
    if queued:
        logger.info("Re-queued %d render(s) that failed on an older version", queued)
    return queued


def cleanup_orphans() -> None:
    """Finish deletes that couldn't complete earlier (Windows keeps files
    locked while ffmpeg or the browser has them open). Only folders that a
    delete explicitly marked are touched -- never anything else."""
    from app.config import settings as app_settings

    root = app_settings.projects_dir
    if not root.exists():
        return
    import shutil

    for d in root.iterdir():
        if d.is_dir() and (d / ".deleted").exists() and db.get_project(d.name) is None:
            shutil.rmtree(d, ignore_errors=True)


def cancel_renders(project_id: str) -> None:
    for j in jobs.active_jobs(project_id, "render"):
        jobs.request_cancel(j["id"])


@jobs.register("process")
def job_process(ctx: jobs.JobContext) -> dict:
    """Everything from a source to ranked (and optionally rendered) clips."""
    pid = ctx.project_id
    assert pid
    params = ctx.params
    cancel_renders(pid)
    ps = project_settings.load(pid)
    db.update_project(pid, status="processing", error_message=None)
    try:
        url = params.get("youtube_url")
        if url:
            ctx.update(0.0, "Starting download...", stage="download")
            section = None
            if ps.range_start or ps.range_end:
                section = (ps.range_start or 0.0, ps.range_end)
            downloaded = False
            if section:
                try:
                    do_download(pid, url, ctx.sub(0.0, 0.15, "download"), section=section)
                    # The file now IS the chosen part: process all of it, and
                    # remember where it came from for the creator's reference.
                    ps = project_settings.update(pid, {"range_start": None, "range_end": None})
                    manifest = storage.read_manifest(pid) or {}
                    manifest["source_section"] = list(section)
                    storage.write_manifest(pid, manifest)
                    downloaded = True
                except jobs.JobCancelled:
                    raise
                except Exception as exc:
                    logger.warning("Section download failed (%s); downloading the full video instead.", exc)
                    ctx.update(0.0, "Downloading the full video instead of just the selected part...")
            if not downloaded:
                do_download(pid, url, ctx.sub(0.0, 0.15, "download"))
        require_source(pid)
        if project_meta(pid).get("has_audio") is False:
            db.update_project(pid, status="ready", error_message=None)
            raise ValidationFailedError(
                "This video has no audio track, so ClipForge can't find moments from what's said.",
                suggestion="You can still make clips by hand: open “Source & range” and use “Cut a clip yourself”.",
            )

        ctx.update(0.15, "Preparing transcription...", stage="transcribe")
        do_transcribe(pid, ctx.sub(0.15, 0.70, "transcribe"), force=bool(params.get("force_transcribe")))

        if ps.clip_mode == "manual":
            # The creator marks the clips themselves: transcribe (so captions
            # and the transcript editor work), but don't pick anything.
            try:
                ensure_preview(pid, ctx.sub(0.70, 1.0, "preview"))
            except jobs.JobCancelled:
                raise
            except Exception as exc:
                logger.warning("Preview proxy failed for %s: %s", pid, exc)
            db.update_project(pid, status="ready")
            ctx.update(1.0, "Transcribed. Mark your clips in Source & range.", stage="done")
            return {"clips": 0, "renders_queued": 0, "message": "Manual mode: no clips were picked automatically."}

        ctx.update(0.70, "Analyzing audio...", stage="analyze")
        do_detect(pid, ctx.sub(0.70, 0.85, "analyze"), min_candidates=max(ps.clip_count * 2, 6))
        ctx.update(0.85, "Ranking clips...", stage="rank")
        payload = do_rank(pid, progress=ctx.sub(0.85, 0.95, "rank"))
        auto_ids = [c["id"] for c in payload["clips"] if c.get("origin") != "manual"]

        rendered = 0
        if ps.auto_render and auto_ids:
            for cid in auto_ids:
                clip_store.update_clip(pid, cid, {"render": {"status": "queued"}})
                jobs.enqueue("render", pid, {"clip_id": cid}, queue="render")
                rendered += 1
        # Some formats (MKV, AVI, HEVC...) don't play in the browser; make a
        # lightweight preview copy for the editor while the clips render.
        try:
            ensure_preview(pid, ctx.sub(0.95, 1.0, "preview"))
        except jobs.JobCancelled:
            raise
        except Exception as exc:
            logger.warning("Preview proxy failed for %s: %s", pid, exc)
        db.update_project(pid, status="ready")
        msg = f"Found {len(auto_ids)} clips." + (f" Rendering {rendered} videos..." if rendered else "")
        ctx.update(1.0, msg, stage="done")
        return {"clips": len(auto_ids), "renders_queued": rendered, "message": payload.get("message")}
    except jobs.JobCancelled:
        db.update_project(pid, status="ready")
        raise
    except Exception as exc:
        from app.errors import ClipForgeError

        if storage.find_source_file(pid) is not None and isinstance(exc, ValidationFailedError):
            db.update_project(pid, status="ready")
        else:
            db.update_project(
                pid, status="error", error_message=exc.message if isinstance(exc, ClipForgeError) else "Processing failed."
            )
        raise


@jobs.register("rerank")
def job_rerank(ctx: jobs.JobContext) -> dict:
    """Re-pick clips (e.g. different length / count) without re-transcribing."""
    pid = ctx.project_id
    assert pid
    cancel_renders(pid)
    ps = project_settings.load(pid)
    ctx.update(0.05, "Re-analyzing moments...", stage="analyze")
    do_detect(pid, ctx.sub(0.05, 0.5, "analyze"), min_candidates=max(ps.clip_count * 2, 6))
    payload = do_rank(pid, progress=ctx.sub(0.5, 0.9, "rank"))
    auto_ids = [c["id"] for c in payload["clips"] if c.get("origin") != "manual"]
    if ps.auto_render:
        for cid in auto_ids:
            clip_store.update_clip(pid, cid, {"render": {"status": "queued"}})
            jobs.enqueue("render", pid, {"clip_id": cid}, queue="render")
    ctx.update(1.0, f"Found {len(auto_ids)} clips.", stage="done")
    return {"clips": len(auto_ids)}


@jobs.register("render")
def job_render(ctx: jobs.JobContext) -> dict:
    pid = ctx.project_id
    assert pid
    clip_id = ctx.params["clip_id"]
    ctx.update(0.0, "Starting render...", stage="render")
    try:
        info = do_render(pid, clip_id, ctx.sub(0.0, 1.0, "render"))
    except NotFoundError:
        # The clip (or project) was deleted / re-picked while this render
        # waited -- that's a cancellation, not a failure. Tidy up its files.
        try:
            for p in storage.renders_dir(pid).glob(f"{clip_id}.*"):
                p.unlink(missing_ok=True)
        except Exception:
            pass
        raise jobs.JobCancelled()
    return {"clip_id": clip_id, "file": info.get("file"), "qc": info.get("qc")}


def enqueue_render(project_id: str, clip_id: str) -> dict:
    for j in jobs.active_jobs(project_id, "render"):
        if j["params"].get("clip_id") == clip_id and j["status"] == "queued":
            return j
    clip_store.update_clip(project_id, clip_id, {"render": {"status": "queued"}})
    return jobs.enqueue("render", project_id, {"clip_id": clip_id}, queue="render")
