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


# --- Duration fitting (grow/shrink a candidate window toward the preset) ---

# Don't reach across a long silence to pad a clip: a >4s gap usually means a
# topic/scene change, and a clip that spans one feels like two clips glued.
CONTEXT_GAP_LIMIT_SECONDS = 4.0
# Portion of the clip that should come BEFORE the peak moment (setup). The
# rest is the event + reaction/payoff, which viewers care about more.
TARGET_SETUP_SHARE = 0.4


@dataclass
class FittedWindow:
    start_idx: int
    end_idx: int
    grew: bool = False
    shrank: bool = False


def fit_window(
    segments: list,
    start_idx: int,
    end_idx: int,
    peak_idx: int | None,
    bounds: DurationBounds,
) -> FittedWindow:
    """Grow or shrink [start_idx, end_idx] (unit indices) toward the preset's
    preferred duration, keeping the peak inside the window. Grows setup
    first until ~40% of the clip precedes the peak, then adds aftermath.
    Refuses to cross long silences unless the clip would otherwise be
    shorter than the preset minimum."""
    n = len(segments)
    if n == 0:
        return FittedWindow(start_idx, end_idx)
    start_idx = max(0, min(start_idx, n - 1))
    end_idx = max(start_idx, min(end_idx, n - 1))
    if peak_idx is None or not (start_idx <= peak_idx <= end_idx):
        peak_idx = (start_idx + end_idx) // 2

    def dur(s: int, e: int) -> float:
        return segments[e].end - segments[s].start

    grew = shrank = False
    target = bounds.preferred_seconds

    # Grow toward the preferred duration.
    while dur(start_idx, end_idx) < target:
        can_back = start_idx > 0
        can_fwd = end_idx < n - 1
        if not can_back and not can_fwd:
            break
        below_min = dur(start_idx, end_idx) < bounds.min_seconds
        back_gap = segments[start_idx].start - segments[start_idx - 1].end if can_back else 1e9
        fwd_gap = segments[end_idx + 1].start - segments[end_idx].end if can_fwd else 1e9
        back_ok = can_back and (back_gap <= CONTEXT_GAP_LIMIT_SECONDS or below_min)
        fwd_ok = can_fwd and (fwd_gap <= CONTEXT_GAP_LIMIT_SECONDS or below_min)
        if not back_ok and not fwd_ok:
            break
        total = dur(start_idx, end_idx)
        setup = segments[peak_idx].start - segments[start_idx].start
        want_back = total <= 0 or (setup / max(total, 1e-6)) < TARGET_SETUP_SHARE
        if want_back and back_ok:
            cand = dur(start_idx - 1, end_idx)
            if cand > bounds.max_seconds and dur(start_idx, end_idx) >= bounds.min_seconds:
                break
            start_idx -= 1
        elif fwd_ok:
            cand = dur(start_idx, end_idx + 1)
            if cand > bounds.max_seconds and dur(start_idx, end_idx) >= bounds.min_seconds:
                break
            end_idx += 1
        else:
            cand = dur(start_idx - 1, end_idx)
            if cand > bounds.max_seconds and dur(start_idx, end_idx) >= bounds.min_seconds:
                break
            start_idx -= 1
        grew = True

    # Shrink when over the maximum: drop whichever edge unit is farther from
    # the peak (setup goes first -- the payoff is what people share).
    while dur(start_idx, end_idx) > bounds.max_seconds and end_idx > start_idx:
        setup = segments[peak_idx].start - segments[start_idx].start
        after = segments[end_idx].end - segments[peak_idx].end
        if start_idx < peak_idx and (setup >= after * 0.6 or end_idx <= peak_idx):
            start_idx += 1
        elif end_idx > peak_idx:
            end_idx -= 1
        elif start_idx < peak_idx:
            start_idx += 1
        else:
            break
        shrank = True

    return FittedWindow(start_idx=start_idx, end_idx=end_idx, grew=grew, shrank=shrank)


def padded_times(
    segments: list,
    start_idx: int,
    end_idx: int,
    media_start: float = 0.0,
    media_end: float | None = None,
    lead_pad: float = 0.12,
    tail_pad: float = 0.45,
) -> tuple[float, float]:
    """Exact cut points: a hair before the first word (so the first syllable
    isn't clipped) and a short breath after the last word (so the clip
    doesn't feel chopped), never overlapping the neighbouring units' speech."""
    start = segments[start_idx].start - lead_pad
    if start_idx > 0:
        start = max(start, segments[start_idx - 1].end + 0.02)
    end = segments[end_idx].end + tail_pad
    if end_idx < len(segments) - 1:
        end = min(end, max(segments[end_idx + 1].start - 0.02, segments[end_idx].end))
    start = max(start, media_start)
    if media_end is not None:
        end = min(end, media_end)
    return round(start, 2), round(max(end, start + 0.5), 2)
