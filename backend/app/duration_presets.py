"""
Duration presets (spec section 13). Every preset is (min, max, preferred) --
min/max are hard bounds a window builder should respect, preferred is what
boundary refinement aims for when it has a choice, but semantic completeness
always wins over hitting the number exactly (never trim a payoff just to
land on the preferred duration).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DurationPreset(str, Enum):
    ULTRA_SHORT = "ultra_short"  # 10-20s
    SHORT = "short"  # 20-35s
    STANDARD = "standard"  # 30-60s
    EXTENDED = "extended"  # 60-90s
    CUSTOM = "custom"


@dataclass
class DurationBounds:
    min_seconds: float
    max_seconds: float
    preferred_seconds: float


_PRESET_BOUNDS: dict[DurationPreset, DurationBounds] = {
    DurationPreset.ULTRA_SHORT: DurationBounds(10.0, 20.0, 15.0),
    DurationPreset.SHORT: DurationBounds(20.0, 35.0, 28.0),
    DurationPreset.STANDARD: DurationBounds(30.0, 60.0, 45.0),
    DurationPreset.EXTENDED: DurationBounds(60.0, 90.0, 75.0),
}


def resolve_bounds(
    preset: DurationPreset,
    custom_min: float | None = None,
    custom_max: float | None = None,
    custom_preferred: float | None = None,
) -> DurationBounds:
    if preset == DurationPreset.CUSTOM:
        if custom_min is None or custom_max is None:
            raise ValueError("custom_min and custom_max are required when preset is 'custom'")
        preferred = custom_preferred if custom_preferred is not None else (custom_min + custom_max) / 2
        if not (custom_min <= preferred <= custom_max):
            preferred = (custom_min + custom_max) / 2
        return DurationBounds(custom_min, custom_max, preferred)
    return _PRESET_BOUNDS[preset]
