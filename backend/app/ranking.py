"""
Phase 4 -- clip ranking.

Takes Phase 3's candidate moments and Phase 5's boundary refinement, and
produces the final ranked, diversified clip selection: several deterministic
sub-scores (never an LLM's subjective score alone, per CLAUDE.md), a
plain-language explanation per clip, and real diversity enforcement so five
clips from the same 90-second span don't all get selected. If fewer than the
requested count are genuinely strong, returns fewer -- never pads with weak
candidates just to hit a quota (spec section 14).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.audio_analysis import EnergyProfile
from app.boundaries import refine_boundaries
from app.duration_presets import DurationBounds
from app.moments import Moment

# Deterministic sub-score weights. Documented and tunable in one place
# rather than scattered magic numbers -- see each _*_score function for
# what each one actually measures.
WEIGHTS = {
    "energy": 1.0,
    "text": 1.0,
    "hook": 1.2,
    "payoff": 1.0,
    "standalone": 0.8,
    "duration_fit": 0.6,
}

PUBLISHABLE_SCORE_THRESHOLD = 1.5  # below this, a candidate isn't "genuinely strong"
OVERLAP_DEDUP_RATIO = 0.4  # >40% overlap (of the shorter clip) counts as "the same moment"
MAX_PER_CATEGORY_BEFORE_PREFERRING_DIVERSITY = 2

DANGLING_OPENERS = {"and", "so", "but", "because", "that", "this", "it", "then", "also", "which"}


@dataclass
class RankedClip:
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


def _hook_score(segments: list, start_idx: int, energy_profile: EnergyProfile) -> float:
    """Does the clip grab attention in its opening ~2 seconds?"""
    first = segments[start_idx]
    opening_end = min(first.start + 2.0, first.end)
    z = max(energy_profile.peak_z_in_range(first.start, opening_end), 0.0)
    text_hit = 1.0 if "!" in first.text or (first.text.isupper() and len(first.text) > 3) else 0.0
    return round(z * 0.6 + text_hit, 3)


def _payoff_score(segments: list, end_idx: int, energy_profile: EnergyProfile) -> float:
    """Does the clip end on a strong beat rather than trailing off mid-thought?"""
    last = segments[end_idx]
    closing_start = max(last.end - 2.0, last.start)
    z = max(energy_profile.peak_z_in_range(closing_start, last.end), 0.0)
    exclaim = min(last.text.count("!"), 2) * 0.3
    return round(z * 0.6 + exclaim, 3)


def _standalone_score(segments: list, start_idx: int) -> float:
    """Penalize openings that clearly depend on unseen prior context (a
    clip should make sense to someone who never watched the source)."""
    first_words = segments[start_idx].text.strip().split()
    if not first_words:
        return 0.0
    opener = first_words[0].strip(".,!?;:\"'").lower()
    if opener in DANGLING_OPENERS:
        return -0.5
    gap_bonus = 0.3 if start_idx == 0 else 0.0
    return round(0.5 + gap_bonus, 3)


def _duration_fit_score(duration: float, bounds: DurationBounds) -> float:
    if duration < bounds.min_seconds or duration > bounds.max_seconds * 1.15:
        return -1.0
    spread = max(bounds.max_seconds - bounds.min_seconds, 1.0)
    distance = abs(duration - bounds.preferred_seconds) / spread
    return round(max(0.0, 1.0 - distance), 3)


def score_and_refine(
    moment: Moment,
    segments: list,
    energy_profile: EnergyProfile,
    bounds: DurationBounds,
) -> RankedClip:
    refined = refine_boundaries(segments, moment.start_idx, moment.end_idx, energy_profile, bounds)
    duration = refined.end - refined.start

    hook = _hook_score(segments, refined.start_idx, energy_profile)
    payoff = _payoff_score(segments, refined.end_idx, energy_profile)
    standalone = _standalone_score(segments, refined.start_idx)
    duration_fit = _duration_fit_score(duration, bounds)
    energy_component = max(moment.signals.get("energy_z", 0.0), 0.0)
    text_component = max(moment.score - energy_component, 0.0)

    total = (
        WEIGHTS["energy"] * energy_component
        + WEIGHTS["text"] * text_component
        + WEIGHTS["hook"] * hook
        + WEIGHTS["payoff"] * payoff
        + WEIGHTS["standalone"] * standalone
        + WEIGHTS["duration_fit"] * duration_fit
    )

    excerpt = " ".join(seg.text for seg in segments[refined.start_idx : refined.end_idx + 1]).strip()

    reason_bits = [moment.reason.rstrip(".")]
    if hook >= 0.8:
        reason_bits.append("strong opening hook")
    if payoff >= 0.8:
        reason_bits.append("clear payoff at the end")
    if standalone < 0:
        reason_bits.append("may need extra context -- opens mid-thought")
    reason = "; ".join(reason_bits) + "."

    return RankedClip(
        id=moment.id,
        start=refined.start,
        end=refined.end,
        category=moment.category,
        total_score=round(total, 2),
        sub_scores={
            "energy": round(energy_component, 2),
            "text": round(text_component, 2),
            "hook": hook,
            "payoff": payoff,
            "standalone": standalone,
            "duration_fit": duration_fit,
        },
        transcript_excerpt=excerpt,
        reason=reason,
        duration_explanation=refined.explanation,
        llm_enriched=moment.llm_enriched,
    )


def _overlap_ratio(a: RankedClip, b: RankedClip) -> float:
    overlap = min(a.end, b.end) - max(a.start, b.start)
    if overlap <= 0:
        return 0.0
    shorter = min(a.end - a.start, b.end - b.start)
    return overlap / shorter if shorter > 0 else 0.0


@dataclass
class ClipSelectionResult:
    clips: list[RankedClip]
    requested_count: int
    considered_count: int
    message: str | None


def select_clips(
    moments: list[Moment],
    segments: list,
    energy_profile: EnergyProfile,
    bounds: DurationBounds,
    requested_count: int,
) -> ClipSelectionResult:
    ranked = [score_and_refine(m, segments, energy_profile, bounds) for m in moments]
    ranked.sort(key=lambda c: c.total_score, reverse=True)
    strong = [c for c in ranked if c.total_score >= PUBLISHABLE_SCORE_THRESHOLD]

    def already_overlaps(candidate: RankedClip, chosen: list[RankedClip]) -> bool:
        return any(_overlap_ratio(candidate, c) > OVERLAP_DEDUP_RATIO for c in chosen)

    selected: list[RankedClip] = []
    skipped_for_diversity: list[RankedClip] = []

    for candidate in strong:
        if already_overlaps(candidate, selected):
            continue
        same_category_count = sum(1 for c in selected if c.category == candidate.category)
        other_category_available = any(c.category != candidate.category for c in strong if c is not candidate)
        if (
            same_category_count >= MAX_PER_CATEGORY_BEFORE_PREFERRING_DIVERSITY
            and other_category_available
            and len(selected) < requested_count
        ):
            skipped_for_diversity.append(candidate)
            continue
        selected.append(candidate)
        if len(selected) >= requested_count:
            break

    # Backfill from diversity-skipped candidates (better a same-category
    # strong clip than an empty slot) before ever touching sub-threshold ones.
    if len(selected) < requested_count:
        for candidate in skipped_for_diversity:
            if already_overlaps(candidate, selected):
                continue
            selected.append(candidate)
            if len(selected) >= requested_count:
                break

    message = None
    if len(selected) < requested_count:
        if not strong:
            message = (
                f"No genuinely strong candidates found (out of {len(ranked)} detected). "
                "This section of the video may not have clip-worthy moments, or try a "
                "different content type."
            )
        else:
            message = (
                f"Only {len(selected)} genuinely strong candidate(s) found -- returning those "
                f"instead of padding to {requested_count} with weaker moments."
            )

    return ClipSelectionResult(
        clips=selected, requested_count=requested_count, considered_count=len(ranked), message=message
    )
