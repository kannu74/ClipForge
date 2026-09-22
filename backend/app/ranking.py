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

import math
from dataclasses import dataclass, field

from app.audio_analysis import EnergyProfile
from app.boundaries import fit_window, padded_times, refine_boundaries
from app.duration_presets import DurationBounds
from app.moments import Moment
from app.titles import heuristic_title

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
    virality: int = 0
    confidence: str = "high"  # "high" = cleared the publishable bar; "low" = backup option
    start_idx: int = 0
    end_idx: int = 0
    title: str = ""
    extra: dict = field(default_factory=dict)


def virality_score(total_score: float) -> int:
    """Map the raw weighted score onto a 1-99 scale for display. Monotonic,
    so ordering is unchanged. The publishable threshold (1.5) lands around
    22, a typical good clip (~4-5) in the 60s-70s, and only clips strong on
    several signals at once reach the 90s."""
    v = 99.0 / (1.0 + math.exp(-(total_score - 3.2) / 1.4))
    return int(max(1, min(99, round(v))))


def _compress_z(z: float) -> float:
    """Loudness z-scores in real gameplay run up to 9-10 (gunshots,
    explosions). Uncompressed, one loud bang outweighed every other signal
    and every clip scored 99. Log-compress so loudness still matters but
    hook/payoff/speech can compete: z=1 -> 1.1, 2 -> 1.8, 4 -> 2.6, 9 -> 3.7."""
    return 1.6 * math.log1p(max(z, 0.0))


def _hook_score(segments: list, start_idx: int, energy_profile: EnergyProfile) -> float:
    """Does the clip grab attention in its opening ~2 seconds?"""
    first = segments[start_idx]
    opening_end = min(first.start + 2.0, first.end)
    z = _compress_z(energy_profile.peak_z_in_range(first.start, opening_end))
    text_hit = 1.0 if "!" in first.text or (first.text.isupper() and len(first.text) > 3) else 0.0
    return round(z * 0.6 + text_hit, 3)


def _payoff_score(segments: list, end_idx: int, energy_profile: EnergyProfile) -> float:
    """Does the clip end on a strong beat rather than trailing off mid-thought?"""
    last = segments[end_idx]
    closing_start = max(last.end - 2.0, last.start)
    z = _compress_z(energy_profile.peak_z_in_range(closing_start, last.end))
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
    media_start: float = 0.0,
    media_end: float | None = None,
) -> RankedClip:
    s_idx, e_idx = moment.start_idx, moment.end_idx
    peak = getattr(moment, "peak_idx", None)
    if peak is not None and s_idx <= peak <= e_idx:
        # Re-grow from a tight core (the peak plus directly-adjacent speech)
        # instead of the detector's coarse window, so the setup/payoff balance
        # is chosen by fit_window rather than by whatever made the detector's
        # window long enough.
        s_idx = e_idx = peak
        if peak - 1 >= moment.start_idx and segments[peak].start - segments[peak - 1].end < 1.0:
            s_idx = peak - 1
        if peak + 1 <= moment.end_idx and segments[peak + 1].start - segments[peak].end < 1.0:
            e_idx = peak + 1
    fitted = fit_window(segments, s_idx, e_idx, peak, bounds)
    refined = refine_boundaries(segments, fitted.start_idx, fitted.end_idx, energy_profile, bounds)
    start, end = padded_times(segments, refined.start_idx, refined.end_idx, media_start, media_end)
    duration = end - start

    hook = _hook_score(segments, refined.start_idx, energy_profile)
    payoff = _payoff_score(segments, refined.end_idx, energy_profile)
    standalone = _standalone_score(segments, refined.start_idx)
    duration_fit = _duration_fit_score(duration, bounds)
    raw_z = max(moment.signals.get("energy_z", 0.0), 0.0)
    energy_component = _compress_z(raw_z)
    text_component = max(moment.score - raw_z, 0.0)

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

    dur_reasons = []
    if fitted.grew:
        dur_reasons.append("added surrounding setup/aftermath to reach the target length")
    if fitted.shrank:
        dur_reasons.append("tightened to stay within the target length")
    if refined.trimmed_filler:
        dur_reasons.append("trimmed a filler-only opening for a cleaner start")
    if refined.extended_for_reaction:
        dur_reasons.append("extended slightly because the reaction was still going")
    if duration < bounds.min_seconds:
        dur_reasons.append("shorter than the preset because there's no more related speech around it")
    if not dur_reasons:
        dur_reasons.append("lands naturally within the target range")
    explanation = f"Recommended duration: {duration:.0f} seconds -- " + ", ".join(dur_reasons) + "."

    total = round(total, 2)
    return RankedClip(
        id=moment.id,
        start=start,
        end=end,
        category=moment.category,
        total_score=total,
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
        duration_explanation=explanation,
        llm_enriched=moment.llm_enriched,
        virality=virality_score(total),
        confidence="high" if total >= PUBLISHABLE_SCORE_THRESHOLD and not getattr(moment, "low_signal", False) else "low",
        start_idx=refined.start_idx,
        end_idx=refined.end_idx,
        title=heuristic_title(excerpt, moment.category),
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
    allow_low_confidence: bool = False,
    media_start: float = 0.0,
    media_end: float | None = None,
) -> ClipSelectionResult:
    """`allow_low_confidence`: when fewer strong clips exist than requested,
    fill the remaining slots with the best non-overlapping backups, each
    explicitly marked confidence="low" (and the message says so) -- never
    silently presented as equal to the strong ones."""
    ranked = [score_and_refine(m, segments, energy_profile, bounds, media_start, media_end) for m in moments]
    ranked.sort(key=lambda c: c.total_score, reverse=True)
    strong = [c for c in ranked if c.confidence == "high"]

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

    n_strong = len(selected)
    if allow_low_confidence and len(selected) < requested_count:
        for candidate in ranked:
            if candidate in selected or already_overlaps(candidate, selected):
                continue
            candidate.confidence = "low"
            selected.append(candidate)
            if len(selected) >= requested_count:
                break

    message = None
    if allow_low_confidence and n_strong < len(selected):
        n_backup = len(selected) - n_strong
        message = (
            f"{n_strong} strong clip{'s' if n_strong != 1 else ''} found. "
            f"{n_backup} more {'are' if n_backup != 1 else 'is a'} lower-confidence backup "
            f"pick{'s' if n_backup != 1 else ''} (marked below) -- review before posting."
        )
        if len(selected) < requested_count:
            message += f" The video only had {len(selected)} distinct sections worth offering."
    elif len(selected) < requested_count:
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
