"""Pydantic request/response schemas for the API."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ContentType(str, Enum):
    GAMING = "gaming"
    FUNNY_GAMING = "funny_gaming"
    HORROR_GAMING = "horror_gaming"
    REACTION = "reaction"
    COMEDY = "comedy"
    COMMENTARY = "commentary"
    STORYTELLING = "storytelling"
    GENERAL_CREATOR = "general_creator"


class ProjectStatus(str, Enum):
    CREATED = "created"
    INGESTING = "ingesting"
    READY = "ready"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    RANKING = "ranking"
    RENDERING = "rendering"
    ERROR = "error"


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content_type: ContentType = ContentType.GENERAL_CREATOR
    settings: dict | None = None


class MediaMetadataOut(BaseModel):
    duration_seconds: float
    width: int
    height: int
    fps: float
    video_codec: str | None
    audio_codec: str | None
    audio_channels: int | None
    has_audio: bool
    file_size_bytes: int
    aspect_ratio: str


class YoutubeIngestRequest(BaseModel):
    url: str = Field(min_length=1)


class ProjectOut(BaseModel):
    id: str
    name: str
    content_type: str
    source_type: str | None
    source_reference: str | None
    status: str
    preset_id: str | None
    error_message: str | None
    created_at: str
    updated_at: str
    metadata: MediaMetadataOut | None = None
    has_transcript: bool = False
    has_moments: bool = False
    has_clips: bool = False
    settings: dict | None = None

    @classmethod
    def from_row(cls, row, *, has_transcript: bool = False, has_moments: bool = False, has_clips: bool = False) -> "ProjectOut":
        import json

        raw_meta = row["metadata_json"] if "metadata_json" in row.keys() else "{}"
        meta_dict = json.loads(raw_meta) if raw_meta else {}
        return cls(
            id=row["id"],
            name=row["name"],
            content_type=row["content_type"],
            source_type=row["source_type"],
            source_reference=row["source_reference"],
            status=row["status"],
            preset_id=row["preset_id"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=MediaMetadataOut(**meta_dict) if meta_dict else None,
            has_transcript=has_transcript,
            has_moments=has_moments,
            has_clips=has_clips,
        )


class GpuInfoOut(BaseModel):
    available: bool
    name: str | None
    vram_total_mb: int | None
    vram_free_mb: int | None
    cuda_available: bool


class HardwareReportOut(BaseModel):
    cpu_cores_logical: int
    cpu_cores_physical: int | None
    ram_total_mb: int
    ram_available_mb: int
    gpu: GpuInfoOut
    ffmpeg_available: bool
    ffmpeg_version: str | None
    ollama_reachable: bool
    ollama_models: list[str]
    recommended_quality_mode: str


# --- Transcription ---

class TranscriptWordOut(BaseModel):
    word: str
    start: float
    end: float
    probability: float | None = None


class TranscriptSegmentOut(BaseModel):
    id: int
    start: float
    end: float
    text: str
    words: list[TranscriptWordOut] = []
    edited: bool = False


class TranscriptOut(BaseModel):
    model_config = {"protected_namespaces": ()}

    project_id: str
    language: str | None
    model_size: str
    segments: list[TranscriptSegmentOut]
    created_at: str


class SegmentEditRequest(BaseModel):
    text: str = Field(min_length=0)


# --- Moment detection ---

class MomentOut(BaseModel):
    id: str
    start: float
    end: float
    category: str
    score: float
    signals: dict
    transcript_excerpt: str
    reason: str
    start_idx: int
    end_idx: int
    llm_enriched: bool


class MomentsOut(BaseModel):
    project_id: str
    content_type: str
    moments: list[MomentOut]
    ollama_used: bool
    created_at: str


# --- Clip ranking (Phase 4/5) ---

class GenerateClipsRequest(BaseModel):
    count: int = Field(default=5, ge=1, le=50)
    duration_preset: str = Field(default="standard")  # ultra_short|short|standard|extended|custom
    custom_min_seconds: float | None = None
    custom_max_seconds: float | None = None
    custom_preferred_seconds: float | None = None


class ClipOut(BaseModel):
    id: str
    start: float
    end: float
    category: str
    total_score: float
    sub_scores: dict
    transcript_excerpt: str
    reason: str
    duration_explanation: str
    llm_enriched: bool
    title: str = ""
    origin: str = "auto"
    edited: bool = False
    virality: int = 0
    confidence: str = "high"
    caption_overrides: dict | None = None
    reframe_overrides: dict | None = None
    caption_words: list | None = None
    render: dict = Field(default_factory=lambda: {"status": "none"})


class ClipPatchRequest(BaseModel):
    start: float | None = None
    end: float | None = None
    title: str | None = Field(default=None, max_length=200)
    caption_overrides: dict | None = None
    reframe_overrides: dict | None = None
    clear_caption_overrides: bool = False
    clear_reframe_overrides: bool = False
    render: bool = False  # enqueue a re-render after applying the edit


class ClipCreateRequest(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    title: str = ""
    render: bool = True


class CaptionWordIn(BaseModel):
    word: str
    start: float
    end: float


class CaptionWordsRequest(BaseModel):
    words: list[CaptionWordIn] | None = None  # None = reset to transcript
    render: bool = False


class ProcessRequest(BaseModel):
    youtube_url: str | None = None
    force_transcribe: bool = False
    settings: dict | None = None


class JobOut(BaseModel):
    id: str
    project_id: str | None
    kind: str
    queue: str
    status: str
    progress: float
    stage: str | None = None
    message: str | None = None
    error: str | None = None
    suggestion: str | None = None
    params: dict = {}
    result: dict | None = None
    created_at: str
    updated_at: str


class ClipsOut(BaseModel):
    project_id: str
    content_type: str
    duration_preset: str
    requested_count: int
    considered_count: int
    message: str | None
    clips: list[ClipOut]
    created_at: str
