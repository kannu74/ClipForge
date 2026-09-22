"""Saved presets (Phase 8)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import presets
from app.models import ContentType

router = APIRouter(prefix="/api/presets", tags=["presets"])


class PresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    content_type: ContentType = ContentType.GENERAL_CREATOR
    settings: dict = {}


@router.get("")
def list_presets() -> list[dict]:
    return presets.list_presets()


@router.post("", status_code=201)
def create_preset(payload: PresetCreate) -> dict:
    return presets.create_preset(payload.name, payload.content_type.value, payload.settings)


@router.delete("/{preset_id}", status_code=204, response_model=None)
def delete_preset(preset_id: str) -> None:
    presets.delete_preset(preset_id)
    return None
