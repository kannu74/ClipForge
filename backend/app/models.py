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

    @classmethod
    def from_row(cls, row) -> "ProjectOut":
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
