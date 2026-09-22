"""
Sentence-level "units" built from Whisper's word timestamps.

Whisper segments are an ASR artifact, not a editorial one: with VAD a single
segment can run 20-30 seconds and contain several sentences, which makes it
impossible to start or end a clip cleanly. Every downstream stage (moment
detection, duration fitting, boundary refinement, captions) works on these
units instead: each is roughly one sentence / breath group, split at
sentence punctuation (English and Devanagari danda), at real pauses between
words, and -- as a last resort -- at commas once a unit gets long.

Units are derived deterministically from transcript.json, so the same
transcript always yields the same unit indices (moments store unit indices).
If the creator edited a segment's text, the original word timings no longer
match the words, so that segment's words are re-timed evenly across its
span -- slightly less precise, but always consistent with what's shown.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SENTENCE_END_RE = re.compile(r"[.?!।॥]+[\"')\]]*$")  # . ? ! । ॥
SOFT_BREAK_RE = re.compile(r"[,;:—-]$")

PAUSE_SPLIT_SECONDS = 0.7
MAX_UNIT_SECONDS = 10.0
HARD_MAX_UNIT_SECONDS = 16.0


@dataclass
class UnitWord:
    word: str
    start: float
    end: float


@dataclass
class Unit:
    id: int
    start: float
    end: float
    text: str
    words: list[UnitWord] = field(default_factory=list)
    segment_id: int = 0


def segment_words(seg: dict) -> list[UnitWord]:
    """The words of a transcript segment, re-timed evenly if the segment's
    text was edited (or Whisper returned no word timings)."""
    raw = seg.get("words") or []
    text = (seg.get("text") or "").strip()
    if raw and not seg.get("edited"):
        words = [
            UnitWord(word=str(w["word"]).strip(), start=float(w["start"]), end=float(w["end"]))
            for w in raw
            if str(w.get("word", "")).strip()
        ]
        if words:
            return words
    tokens = text.split()
    if not tokens:
        return []
    start, end = float(seg["start"]), float(seg["end"])
    span = max(end - start, 0.01)
    weights = [max(len(t), 1) for t in tokens]
    total = float(sum(weights))
    out: list[UnitWord] = []
    t = start
    for tok, w in zip(tokens, weights):
        d = span * (w / total)
        out.append(UnitWord(word=tok, start=round(t, 3), end=round(t + d, 3)))
        t += d
    return out


def build_units(segments: list[dict]) -> list[Unit]:
    units: list[Unit] = []

    def flush(buf: list[UnitWord], seg_id: int) -> None:
        if not buf:
            return
        units.append(
            Unit(
                id=len(units),
                start=round(buf[0].start, 3),
                end=round(buf[-1].end, 3),
                text=" ".join(w.word for w in buf).strip(),
                words=list(buf),
                segment_id=seg_id,
            )
        )

    for seg in segments:
        words = segment_words(seg)
        seg_id = int(seg.get("id", 0))
        buf: list[UnitWord] = []
        for i, w in enumerate(words):
            buf.append(w)
            nxt = words[i + 1] if i + 1 < len(words) else None
            dur = buf[-1].end - buf[0].start
            gap = (nxt.start - w.end) if nxt else 0.0
            if nxt is None:
                break
            if SENTENCE_END_RE.search(w.word) and dur >= 0.6:
                flush(buf, seg_id)
                buf = []
            elif gap >= PAUSE_SPLIT_SECONDS and dur >= 0.4:
                flush(buf, seg_id)
                buf = []
            elif dur >= MAX_UNIT_SECONDS and (SOFT_BREAK_RE.search(w.word) or gap >= 0.25):
                flush(buf, seg_id)
                buf = []
            elif dur >= HARD_MAX_UNIT_SECONDS:
                flush(buf, seg_id)
                buf = []
        flush(buf, seg_id)
    return units


def units_from_transcript(transcript: dict) -> list[Unit]:
    return build_units(transcript.get("segments") or [])


def words_in_range(units: list[Unit], start: float, end: float) -> list[UnitWord]:
    """All words whose midpoint falls inside [start, end]."""
    out: list[UnitWord] = []
    for u in units:
        if u.end < start or u.start > end:
            continue
        for w in u.words:
            mid = (w.start + w.end) / 2
            if start <= mid <= end:
                out.append(w)
    return out
