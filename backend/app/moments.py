"""
Phase 3 -- intelligent moment detection.

Combines two deterministic signals (never relies on an LLM's subjective
score alone, per CLAUDE.md):
  1. Audio energy: a short-time RMS loudness spike relative to the rest of
     the video (screams, hype, sudden loud reactions).
  2. Text signals: exclamation marks, ALL-CAPS words, and a content-type-
     aware keyword lexicon covering English, Hindi and Hinglish slang.

Candidates are built as WINDOWS of transcript segments (a peak segment plus
its neighbors as setup/reaction), not single timestamps -- "a scream alone
is a weaker clip than setup -> suspense -> event -> scream -> reaction."
Full multi-signal ranking, diversity enforcement, and precise boundary
optimization are later phases (4 and 5); this phase's job is only to
produce a plausible, roughly-ordered candidate list.

If Ollama is reachable, each candidate optionally gets LLM enrichment
(category confirmation + a human-readable reason). If not, detection still
works end-to-end on deterministic signals alone.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from app.audio_analysis import EnergyProfile
from app.llm import OllamaClient
from app.logging_config import get_logger

logger = get_logger("moments")

MIN_DURATION = 10.0
MAX_DURATION = 90.0
SEGMENT_GAP_MERGE_THRESHOLD = 3.0  # seconds; neighbor segments closer than this can join a window
PEAK_SCORE_THRESHOLD = 0.9

# Content-type -> which categories are even plausible for it (used for
# tie-breaking and for skipping irrelevant lexicon noise).
CONTENT_TYPE_CATEGORIES: dict[str, list[str]] = {
    "gaming": ["clutch", "fail", "rage", "surprise", "funny", "reaction"],
    "funny_gaming": ["funny", "fail", "surprise", "reaction"],
    "horror_gaming": ["scare", "surprise", "reaction"],
    "reaction": ["reaction", "surprise", "funny"],
    "comedy": ["funny", "surprise", "reaction"],
    "commentary": ["story", "surprise", "funny", "reaction"],
    "storytelling": ["story", "surprise", "reaction"],
    "general_creator": ["reaction", "surprise", "funny", "story"],
}

# English + Hindi/Hinglish slang + gaming terminology, deliberately NOT
# translated -- matching is done on the transcript as spoken.
KEYWORD_LEXICON: dict[str, list[str]] = {
    "funny": ["lol", "lmao", "haha", "hilarious", "funny", "ajeeb", "comedy", "joke", "mazak", "majak"],
    "scare": ["scary", "horror", "bhoot", "ghost", "jump scare", "daraya", "dar gaya", "spooky", "darr"],
    "rage": ["rage", "angry", "gussa", "stupid", "hate this", "ridiculous", "bakwas", "i hate", "garbage", "so annoying"],
    "clutch": ["clutch", "ace", "1v1", "1v5", "no way", "insane", "unbelievable", "let's go", "letsgo", "gg", "poggers", "clean"],
    "fail": ["fail", "failed", "rip", "dead", "oops", "screwed up", "mistake", "noob", "bruh", "i died"],
    "surprise": ["no way", "are you serious", "kya", "seriously", "omg", "oh my god", "wait what", "huh", "what the"],
    "reaction": ["bhai", "yaar", "dude", "bro", "what the hell", "wtf", "arey"],
    "story": ["so basically", "let me tell you", "this one time", "story time", "kahani"],
}

_CAPS_WORD_RE = re.compile(r"\b[A-Z]{2,}\b")


@dataclass
class Moment:
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
    llm_enriched: bool = False
    peak_idx: int | None = None
    low_signal: bool = False


def _textual_signals(text: str, allowed_categories: list[str]) -> dict:
    lower = text.lower()
    matches: dict[str, list[str]] = {}
    for category in allowed_categories:
        hits = [kw for kw in KEYWORD_LEXICON.get(category, []) if kw in lower]
        if hits:
            matches[category] = hits
    return {
        "exclaims": text.count("!"),
        "caps_words": len(_CAPS_WORD_RE.findall(text)),
        "keyword_matches": matches,
    }


def _text_score(signals: dict) -> float:
    score = 0.0
    score += min(signals["exclaims"], 3) * 0.5
    score += min(signals["caps_words"], 3) * 0.4
    score += sum(len(v) for v in signals["keyword_matches"].values()) * 0.6
    return score


def _dominant_category(signals_by_segment: list[dict], allowed_categories: list[str]) -> str | None:
    tally: dict[str, int] = {}
    for sig in signals_by_segment:
        for category, hits in sig["keyword_matches"].items():
            tally[category] = tally.get(category, 0) + len(hits)
    if not tally:
        return None
    # Tie-break using the content type's category priority order.
    best = max(
        tally.items(),
        key=lambda kv: (kv[1], -allowed_categories.index(kv[0]) if kv[0] in allowed_categories else -99),
    )
    return best[0]


def _build_window(segments: list, peak_idx: int) -> tuple[int, int]:
    start_idx = end_idx = peak_idx
    if peak_idx > 0 and segments[peak_idx].start - segments[peak_idx - 1].end < SEGMENT_GAP_MERGE_THRESHOLD:
        start_idx = peak_idx - 1
    if (
        peak_idx < len(segments) - 1
        and segments[peak_idx + 1].start - segments[peak_idx].end < SEGMENT_GAP_MERGE_THRESHOLD
    ):
        end_idx = peak_idx + 1

    def duration() -> float:
        return segments[end_idx].end - segments[start_idx].start

    # Expand toward MIN_DURATION using whichever neighbor is available.
    while duration() < MIN_DURATION and (start_idx > 0 or end_idx < len(segments) - 1):
        if start_idx > 0:
            start_idx -= 1
        elif end_idx < len(segments) - 1:
            end_idx += 1

    # Trim toward MAX_DURATION, preferring to cut from the start (keep the
    # payoff/reaction on the end -- "don't cut before the reaction").
    while duration() > MAX_DURATION and start_idx < peak_idx:
        start_idx += 1

    return start_idx, end_idx


def detect_moments(
    content_type: str,
    segments: list,  # transcription.Segment-like: .start .end .text
    energy_profile: EnergyProfile,
    ollama_client: OllamaClient | None = None,
    min_candidates: int = 0,
    max_llm_enrichments: int = 15,
) -> tuple[list[Moment], bool]:
    """`min_candidates`: if strong peaks yield fewer candidates than this,
    add the best remaining (lower-signal) sections, flagged `low_signal`, so
    ranking has enough material to offer clearly-labelled backup options."""
    if not segments:
        return [], False

    allowed_categories = CONTENT_TYPE_CATEGORIES.get(content_type, CONTENT_TYPE_CATEGORIES["general_creator"])

    per_segment_signals = [_textual_signals(seg.text, allowed_categories) for seg in segments]
    per_segment_energy_z = [energy_profile.peak_z_in_range(seg.start, seg.end) for seg in segments]
    per_segment_score = [
        per_segment_energy_z[i] + _text_score(per_segment_signals[i]) for i in range(len(segments))
    ]

    # Candidate peaks: local-ish maxima above threshold, highest first.
    peak_indices = sorted(
        [i for i, s in enumerate(per_segment_score) if s >= PEAK_SCORE_THRESHOLD],
        key=lambda i: per_segment_score[i],
        reverse=True,
    )

    ollama_client = ollama_client or OllamaClient()
    ollama_reachable = ollama_client.is_reachable()
    ollama_used = False

    moments: list[Moment] = []
    claimed_ranges: list[tuple[float, float]] = []

    for peak_idx in peak_indices:
        start_idx, end_idx = _build_window(segments, peak_idx)
        start, end = segments[start_idx].start, segments[end_idx].end

        # Skip if this window heavily overlaps one we already accepted --
        # real diversity enforcement is Phase 4, this is just de-dup.
        if any(not (end <= c0 or start >= c1) for c0, c1 in claimed_ranges):
            overlap_too_much = any(
                (min(end, c1) - max(start, c0)) > 0.6 * min(end - start, c1 - c0)
                for c0, c1 in claimed_ranges
                if not (end <= c0 or start >= c1)
            )
            if overlap_too_much:
                continue

        window_signals = per_segment_signals[start_idx : end_idx + 1]
        category = _dominant_category(window_signals, allowed_categories) or (
            allowed_categories[0] if per_segment_energy_z[peak_idx] >= PEAK_SCORE_THRESHOLD else None
        )
        if category is None:
            continue

        excerpt = " ".join(seg.text for seg in segments[start_idx : end_idx + 1]).strip()
        energy_z = round(per_segment_energy_z[peak_idx], 2)
        keyword_hits = sorted({kw for sig in window_signals for kws in sig["keyword_matches"].values() for kw in kws})

        reason_parts = []
        if energy_z >= 1.0:
            reason_parts.append(f"loud moment ({energy_z:+.1f}σ above the video's average energy)")
        if keyword_hits:
            reason_parts.append(f"matched '{category}' language: {', '.join(keyword_hits[:4])}")
        reason = "Candidate because of " + " and ".join(reason_parts) + "." if reason_parts else "Energy/text signal peak."

        moment = Moment(
            id=uuid.uuid4().hex[:12],
            start=round(start, 2),
            end=round(end, 2),
            category=category,
            score=round(per_segment_score[peak_idx], 2),
            signals={
                "energy_z": energy_z,
                "keyword_matches": keyword_hits,
                "exclaims": per_segment_signals[peak_idx]["exclaims"],
                "caps_words": per_segment_signals[peak_idx]["caps_words"],
            },
            transcript_excerpt=excerpt,
            reason=reason,
            start_idx=start_idx,
            end_idx=end_idx,
            llm_enriched=False,
            peak_idx=peak_idx,
        )

        if ollama_reachable and sum(1 for m in moments if m.llm_enriched) < max_llm_enrichments:
            enrichment = ollama_client.enrich_moment(excerpt, content_type, category)
            if enrichment:
                ollama_used = True
                moment.category = enrichment.get("category", moment.category)
                adjustment = enrichment.get("score_adjustment", 0)
                try:
                    moment.score = round(moment.score + float(adjustment), 2)
                except (TypeError, ValueError):
                    pass
                moment.reason = enrichment.get("reason", moment.reason)
                moment.llm_enriched = True

        moments.append(moment)
        claimed_ranges.append((start, end))

    if len(moments) < min_candidates:
        fallback_order = sorted(range(len(segments)), key=lambda i: per_segment_score[i], reverse=True)
        default_category = "story" if "story" in allowed_categories else allowed_categories[0]
        for idx in fallback_order:
            if len(moments) >= min_candidates:
                break
            start_idx, end_idx = _build_window(segments, idx)
            start, end = segments[start_idx].start, segments[end_idx].end
            if any((min(end, c1) - max(start, c0)) > 0.3 * max(min(end - start, c1 - c0), 1e-6) for c0, c1 in claimed_ranges):
                continue
            window_signals = per_segment_signals[start_idx : end_idx + 1]
            category = _dominant_category(window_signals, allowed_categories) or default_category
            excerpt = " ".join(seg.text for seg in segments[start_idx : end_idx + 1]).strip()
            if len(excerpt.split()) < 4:
                continue
            moments.append(
                Moment(
                    id=uuid.uuid4().hex[:12],
                    start=round(start, 2),
                    end=round(end, 2),
                    category=category,
                    score=round(per_segment_score[idx], 2),
                    signals={
                        "energy_z": round(per_segment_energy_z[idx], 2),
                        "keyword_matches": sorted({kw for sig in window_signals for kws in sig["keyword_matches"].values() for kw in kws}),
                        "exclaims": per_segment_signals[idx]["exclaims"],
                        "caps_words": per_segment_signals[idx]["caps_words"],
                    },
                    transcript_excerpt=excerpt,
                    reason="Lower-signal section -- included as a backup option, not a detected highlight.",
                    start_idx=start_idx,
                    end_idx=end_idx,
                    peak_idx=idx,
                    low_signal=True,
                )
            )
            claimed_ranges.append((start, end))

    moments.sort(key=lambda m: m.score, reverse=True)
    return moments, ollama_used


def moment_to_dict(m: Moment) -> dict:
    return {
        "id": m.id,
        "start": m.start,
        "end": m.end,
        "category": m.category,
        "score": m.score,
        "signals": m.signals,
        "transcript_excerpt": m.transcript_excerpt,
        "reason": m.reason,
        "start_idx": m.start_idx,
        "end_idx": m.end_idx,
        "llm_enriched": m.llm_enriched,
        "peak_idx": m.peak_idx,
        "low_signal": m.low_signal,
    }


def moment_from_dict(m: dict) -> Moment:
    return Moment(
        id=m["id"],
        start=m["start"],
        end=m["end"],
        category=m["category"],
        score=m["score"],
        signals=m.get("signals") or {},
        transcript_excerpt=m.get("transcript_excerpt", ""),
        reason=m.get("reason", ""),
        start_idx=m["start_idx"],
        end_idx=m["end_idx"],
        llm_enriched=m.get("llm_enriched", False),
        peak_idx=m.get("peak_idx"),
        low_signal=m.get("low_signal", False),
    )
