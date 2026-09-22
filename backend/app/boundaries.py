"""
Phase 5 -- boundary optimization.

Phase 3's window builder picks WHICH segments belong to a candidate
(peak + neighboring context/reaction). This module refines the exact
start/end within that choice:
  - trims a leading filler-only segment ("um", "so", "okay...") so the
    clip opens on real content instead of dead air
  - extends the end if the reaction is clearly still going (energy still
    elevated right at the current cutoff) rather than chopping it off
  - never violates semantic completeness for the sake of hitting a
    duration number exactly -- extending past max_seconds by a small
    tolerance to finish a reaction is preferred over cutting it off,
    per the spec's "don't remove the final 5 seconds if they're the
    payoff" example.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.audio_analysis import EnergyProfile
from app.duration_presets import DurationBounds

FILLER_WORDS = {
    "um", "uh", "so", "okay", "ok", "alright", "right", "well",
    "like", "hmm", "actually", "yeah", "hey", "arey", "acha", "haan",
}
MAX_FILLER_SEGMENT_SECONDS = 1.5
REACTION_EXTEND_GAP_THRESHOLD = 2.0
REACTION_EXTEND_ENERGY_Z = 1.0
MAX_DURATION_OVERRUN_RATIO = 1.15  # allow finishing a reaction up to 15% past max_seconds


@dataclass
class RefinedWindow:
    start_idx: int
    end_idx: int
    start: float
    end: float
    explanation: str
    trimmed_filler: bool = False
    extended_for_reaction: bool = False


def _is_filler_only(text: str) -> bool:
    words = [w.strip(".,!?;:\"'").lower() for w in text.split()]
    words = [w for w in words if w]
    return bool(words) and all(w in FILLER_WORDS for w in words)


def refine_boundaries(
    segments: list,
    start_idx: int,
    end_idx: int,
    energy_profile: EnergyProfile,
    bounds: DurationBounds,
) -> RefinedWindow:
    trimmed_filler = False
    extended_for_reaction = False

    # 1. Trim a leading filler-only segment, as long as there's still
    # something left in the window and we don't drop below the minimum.
    while start_idx < end_idx:
        seg = segments[start_idx]
        seg_duration = seg.end - seg.start
        if seg_duration <= MAX_FILLER_SEGMENT_SECONDS and _is_filler_only(seg.text):
            # Safe by construction: start_idx < end_idx means at least one
            # segment remains, so trimming a pure-filler opener never
            # empties the window. It can leave the window short of the
            # preset's min_seconds, but that's Phase 3's window-builder's
            # job to have avoided -- boundary refinement shouldn't keep
            # dead air just to pad toward a duration target.
            start_idx += 1
            trimmed_filler = True
            continue
        break

    # 2. Extend the end if the reaction is clearly still going.
    while end_idx < len(segments) - 1:
        next_seg = segments[end_idx + 1]
        prospective_duration = next_seg.end - segments[start_idx].start
        if prospective_duration > bounds.max_seconds * MAX_DURATION_OVERRUN_RATIO:
            break
        gap = next_seg.start - segments[end_idx].end
        still_loud = energy_profile.peak_z_in_range(
            max(segments[end_idx].end - 0.5, segments[end_idx].start), segments[end_idx].end
        ) >= REACTION_EXTEND_ENERGY_Z
        if gap <= REACTION_EXTEND_GAP_THRESHOLD and still_loud:
            end_idx += 1
            extended_for_reaction = True
            continue
        break

    start = segments[start_idx].start
    end = segments[end_idx].end
    duration = end - start

    reasons = []
    if trimmed_filler:
        reasons.append("trimmed a filler-only opening for a cleaner start")
    if extended_for_reaction:
        reasons.append("extended slightly because the reaction was still going")
    if not reasons:
        if duration <= bounds.preferred_seconds * 1.2:
            reasons.append("lands naturally within the target range")
        else:
            reasons.append("kept the full setup-to-reaction arc intact rather than cutting it short")

    explanation = f"Recommended duration: {duration:.0f} seconds -- " + ", ".join(reasons) + "."

    return RefinedWindow(
        start_idx=start_idx,
        end_idx=end_idx,
        start=round(start, 2),
        end=round(end, 2),
        explanation=explanation,
        trimmed_filler=trimmed_filler,
        extended_for_reaction=extended_for_reaction,
    )
