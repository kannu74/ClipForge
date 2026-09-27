"""
Per-project settings: what to process (source range), how many clips and how
long, caption styling, reframing, and render quality. Stored as JSON in the
projects.settings_json column; every read goes through `load()` so missing
keys (older projects, partial updates) always get sane defaults.

Individual clips can override `captions` and `reframe` (see clip_store.py);
the effective settings for a render are project settings + clip overrides.
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app import db

CaptionStyleName = Literal[
    "bold_pop", "karaoke", "clean", "boxed", "horror", "neon",
    "hormozi", "highlighter", "typewriter", "meme", "cinema", "none",
]
CaptionPosition = Literal["top", "upper", "middle", "lower", "bottom"]
CaptionScript = Literal["as_spoken", "roman", "devanagari"]
ReframeMode = Literal["auto", "fill", "fit_blur", "track", "split", "original"]
AspectRatio = Literal["9:16", "1:1", "4:5", "16:9"]


class CaptionSettings(BaseModel):
    enabled: bool = True
    style: CaptionStyleName = "bold_pop"
    position: CaptionPosition = "lower"
    font_scale: float = Field(default=1.0, ge=0.5, le=2.0)
    words_per_line: int = Field(default=3, ge=1, le=8)
    max_lines: int = Field(default=1, ge=1, le=3)
    uppercase: bool = True
    text_color: str = "#FFFFFF"
    highlight_color: str = "#FFE14D"
    outline_color: str = "#000000"
    font: str = ""  # empty = the style's default font
    script: CaptionScript = "as_spoken"
    emphasize_keywords: bool = True
    # Roman Hinglish: unify variant spellings ("nahin"/"nhi" -> "nahi").
    unify_spelling: bool = False
    # Star out swear words ("f**k") for Reels/Shorts friendliness.
    mask_profanity: bool = False
    # Hook title shown at the top of the clip (the clip's title text).
    title_overlay: bool = False
    title_seconds: float = Field(default=3.0, ge=0, le=600)  # 0 = whole clip

    @field_validator("text_color", "highlight_color", "outline_color")
    @classmethod
    def _hex(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("#"):
            v = "#" + v
        if len(v) != 7 or any(c not in "0123456789abcdefABCDEF" for c in v[1:]):
            raise ValueError("colors must be #RRGGBB")
        return v.upper()


class FacecamRect(BaseModel):
    """Normalized (0-1) rectangle within the source frame."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class ReframeSettings(BaseModel):
    aspect: AspectRatio = "9:16"
    mode: ReframeMode = "auto"
    facecam: FacecamRect | None = None
    split_ratio: float = Field(default=0.4, ge=0.2, le=0.6)  # share of height for the facecam panel
    facecam_on_top: bool = True
    # Manual horizontal focus for "fill" (0 = left edge, 0.5 = center, 1 = right).
    focus_x: float = Field(default=0.5, ge=0, le=1)


class RenderSettings(BaseModel):
    resolution: Literal[720, 1080] = 1080
    quality: Literal["fast", "balanced", "high"] = "balanced"


class ProjectSettings(BaseModel):
    clip_count: int = Field(default=8, ge=1, le=30)
    duration_preset: str = "standard"
    custom_min_seconds: float | None = None
    custom_max_seconds: float | None = None
    range_start: float | None = Field(default=None, ge=0)
    range_end: float | None = Field(default=None, ge=0)
    whisper_model: str | None = None
    language: str = ""  # "" = auto-detect
    # "auto": ClipForge picks the clips. "manual": transcribe only, then the creator marks clips by hand.
    clip_mode: Literal["auto", "manual"] = "auto"
    auto_render: bool = True
    include_backup_clips: bool = True
    captions: CaptionSettings = CaptionSettings()
    reframe: ReframeSettings = ReframeSettings()
    render: RenderSettings = RenderSettings()


def load(project_id: str) -> ProjectSettings:
    row = db.get_project(project_id)
    raw = {}
    if row is not None:
        try:
            raw = json.loads(row["settings_json"] or "{}")
        except (TypeError, ValueError):
            raw = {}
    try:
        return ProjectSettings(**raw)
    except Exception:
        return ProjectSettings()


def save(project_id: str, settings: ProjectSettings) -> ProjectSettings:
    db.update_project(project_id, settings_json=settings.model_dump_json())
    return settings


def deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def update(project_id: str, patch: dict) -> ProjectSettings:
    current = load(project_id).model_dump()
    merged = deep_merge(current, patch)
    new = ProjectSettings(**merged)
    return save(project_id, new)
