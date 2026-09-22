"""
The project's clip list (clips/clips.json): the ranked clips the pipeline
proposed plus everything the creator did to them -- trimmed start/end,
retitled, edited caption text, per-clip caption/reframe overrides, manual
clips they added -- and each clip's render status.

All writes go through a per-project lock: the render worker, the pipeline
and API edits can touch the same file concurrently.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app import project_settings, storage
from app.errors import NotFoundError, ValidationFailedError
from app.project_settings import CaptionSettings, ProjectSettings, ReframeSettings, deep_merge

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()

MIN_CLIP_SECONDS = 1.0
MAX_CLIP_SECONDS = 180.0


def _lock(project_id: str) -> threading.RLock:
    with _locks_guard:
        if project_id not in _locks:
            _locks[project_id] = threading.RLock()
        return _locks[project_id]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_clip_fields() -> dict:
    return {
        "title": "",
        "origin": "auto",
        "edited": False,
        "virality": 0,
        "confidence": "high",
        "caption_overrides": None,
        "reframe_overrides": None,
        "caption_words": None,
        "render": {"status": "none"},
    }


def normalize_clip(c: dict) -> dict:
    out = default_clip_fields()
    out.update(c)
    out["render"] = {"status": "none", **(c.get("render") or {})}
    return out


def load(project_id: str) -> dict | None:
    with _lock(project_id):
        payload = storage.read_json(storage.clips_path(project_id))
        if payload is None:
            return None
        payload["clips"] = [normalize_clip(c) for c in payload.get("clips", [])]
        return payload


def save(project_id: str, payload: dict) -> None:
    with _lock(project_id):
        storage.write_json(storage.clips_path(project_id), payload)


def mutate(project_id: str, fn) -> Any:
    """Load, apply fn(payload) under the lock, save. Returns fn's result."""
    with _lock(project_id):
        payload = load(project_id)
        if payload is None:
            raise NotFoundError("No clips yet.", suggestion="Process the video first.")
        result = fn(payload)
        save(project_id, payload)
        return result


def get_clip(project_id: str, clip_id: str) -> dict:
    payload = load(project_id)
    if payload is None:
        raise NotFoundError("No clips yet.", suggestion="Process the video first.")
    for c in payload["clips"]:
        if c["id"] == clip_id:
            return c
    raise NotFoundError("That clip doesn't exist.", suggestion="It may have been deleted or regenerated.")


def update_clip(project_id: str, clip_id: str, patch: dict) -> dict:
    def fn(payload: dict) -> dict:
        for c in payload["clips"]:
            if c["id"] == clip_id:
                for key in ("caption_overrides", "reframe_overrides"):
                    if key in patch and patch[key] is not None and c.get(key):
                        patch[key] = deep_merge(c[key], patch[key])
                c.update(patch)
                return c
        raise NotFoundError("That clip doesn't exist.")

    return mutate(project_id, fn)


def validate_range(start: float, end: float, media_duration: float | None) -> tuple[float, float]:
    if start < 0:
        start = 0.0
    if media_duration:
        end = min(end, media_duration)
    if end - start < MIN_CLIP_SECONDS:
        raise ValidationFailedError(
            "That clip is too short.", suggestion=f"Clips need to be at least {MIN_CLIP_SECONDS:.0f} second long."
        )
    if end - start > MAX_CLIP_SECONDS:
        raise ValidationFailedError(
            "That clip is too long.", suggestion=f"Keep clips under {MAX_CLIP_SECONDS / 60:.0f} minutes."
        )
    return round(start, 2), round(end, 2)


def add_manual_clip(project_id: str, start: float, end: float, title: str, excerpt: str, content_type: str) -> dict:
    clip = normalize_clip(
        {
            "id": "m" + uuid.uuid4().hex[:11],
            "start": start,
            "end": end,
            "category": "manual",
            "total_score": 0.0,
            "sub_scores": {},
            "transcript_excerpt": excerpt,
            "reason": "Added manually.",
            "duration_explanation": f"Manual clip: {end - start:.0f} seconds, exactly as selected.",
            "llm_enriched": False,
            "title": title or "My clip",
            "origin": "manual",
            "confidence": "high",
            "virality": 0,
        }
    )
    with _lock(project_id):
        payload = load(project_id)
        if payload is None:
            payload = {
                "project_id": project_id,
                "content_type": content_type,
                "duration_preset": "custom",
                "requested_count": 0,
                "considered_count": 0,
                "message": None,
                "clips": [],
                "created_at": _now(),
            }
        payload["clips"].insert(0, clip)
        save(project_id, payload)
    return clip


def delete_clip(project_id: str, clip_id: str) -> None:
    def fn(payload: dict) -> None:
        before = len(payload["clips"])
        payload["clips"] = [c for c in payload["clips"] if c["id"] != clip_id]
        if len(payload["clips"]) == before:
            raise NotFoundError("That clip doesn't exist.")

    mutate(project_id, fn)
    rdir = storage.renders_dir(project_id)
    for p in rdir.glob(f"{clip_id}.*"):
        try:
            p.unlink()
        except OSError:
            pass


def effective_settings(ps: ProjectSettings, clip: dict) -> tuple[CaptionSettings, ReframeSettings]:
    cap = ps.captions.model_dump()
    ref = ps.reframe.model_dump()
    if clip.get("caption_overrides"):
        cap = deep_merge(cap, clip["caption_overrides"])
    if clip.get("reframe_overrides"):
        ref = deep_merge(ref, clip["reframe_overrides"])
    return CaptionSettings(**cap), ReframeSettings(**ref)


def render_hash(ps: ProjectSettings, clip: dict, transcript_rev: int = 0) -> str:
    cap, ref = effective_settings(ps, clip)
    blob = json.dumps(
        {
            "start": clip["start"],
            "end": clip["end"],
            "cap": cap.model_dump(),
            "ref": ref.model_dump(),
            "words": clip.get("caption_words"),
            "render": ps.render.model_dump(),
            "rev": transcript_rev if not clip.get("caption_words") else 0,
            "title": clip.get("title", "") if cap.title_overlay else "",
            "v": 1,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def with_staleness(project_id: str, payload: dict) -> dict:
    """Annotate each clip's render with `stale` (settings changed since it
    was rendered) so the UI can offer a re-render."""
    ps = project_settings.load(project_id)
    t = storage.read_json(storage.transcript_path(project_id)) or {}
    rev = int(t.get("revision") or 0)
    for c in payload.get("clips", []):
        r = c.get("render") or {}
        if r.get("status") == "done":
            r["stale"] = r.get("hash") != render_hash(ps, c, rev)
        c["render"] = r
    return payload
