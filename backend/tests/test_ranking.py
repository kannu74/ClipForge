from types import SimpleNamespace

import numpy as np

from app.audio_analysis import EnergyProfile
from app.duration_presets import DurationPreset, resolve_bounds
from app.moments import Moment
from app.ranking import (
    _duration_fit_score,
    _hook_score,
    _payoff_score,
    _standalone_score,
    select_clips,
)


def _seg(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text)


def _flat_profile(n=20) -> EnergyProfile:
    rms = np.array([0.1] * n)
    return EnergyProfile(window_seconds=0.5, rms=rms, rms_db=20 * np.log10(rms), mean_rms=0.1, std_rms=0.0)


def _loud_profile_2_to_4() -> EnergyProfile:
    rms = np.array([0.05] * 4 + [1.0] * 4 + [0.05] * 4)  # loud 2.0-4.0s
    return EnergyProfile(
        window_seconds=0.5, rms=rms, rms_db=20 * np.log10(rms),
        mean_rms=float(np.mean(rms)), std_rms=float(np.std(rms)),
    )


# --- sub-score unit checks ---

def test_hook_score_rewards_loud_energetic_opening():
    segments = [_seg(0.0, 2.0, "WAIT WHAT?!"), _seg(2.0, 4.0, "okay never mind")]
    profile = _quiet_then_loud()
    loud_opening = _hook_score(segments, 0, profile)
    quiet_opening = _hook_score(segments, 1, profile)
    assert loud_opening > quiet_opening


def _quiet_then_loud() -> EnergyProfile:
    rms = np.array([1.0] * 4 + [0.05] * 4)  # loud 0-2s, quiet 2-4s
    return EnergyProfile(
        window_seconds=0.5, rms=rms, rms_db=20 * np.log10(rms),
        mean_rms=float(np.mean(rms)), std_rms=float(np.std(rms)),
    )


def test_payoff_score_rewards_strong_ending():
    segments = [_seg(0.0, 2.0, "we walked in"), _seg(2.0, 4.0, "AND THEN IT SCREAMED!!")]
    score = _payoff_score(segments, 1, _loud_profile_2_to_4())
    flat_score = _payoff_score(segments, 1, _flat_profile())
    assert score > flat_score


def test_standalone_score_penalizes_dangling_opener():
    segments_dangling = [_seg(0.0, 2.0, "and that's when everything went wrong")]
    segments_fresh = [_seg(0.0, 2.0, "the boss fight finally started")]
    assert _standalone_score(segments_dangling, 0) < _standalone_score(segments_fresh, 0)


def test_duration_fit_score_peaks_near_preferred():
    bounds = resolve_bounds(DurationPreset.STANDARD)  # 30-60, preferred 45
    at_preferred = _duration_fit_score(45.0, bounds)
    at_edge = _duration_fit_score(31.0, bounds)
    way_outside = _duration_fit_score(200.0, bounds)
    assert at_preferred > at_edge > way_outside
    assert way_outside == -1.0


# --- select_clips: the actually important behavior ---

def _make_moment(id_, start, end, category, score, energy_z, start_idx, end_idx, text="content"):
    return Moment(
        id=id_, start=start, end=end, category=category, score=score,
        signals={"energy_z": energy_z, "keyword_matches": [], "exclaims": 0, "caps_words": 0},
        transcript_excerpt=text, reason="test moment", start_idx=start_idx, end_idx=end_idx,
    )


def test_select_clips_never_pads_with_weak_candidates():
    """3 moments requested, but only 1 clears the publishable threshold --
    must return 1, not pad to 3, and must explain why."""
    segments = [
        _seg(0.0, 2.0, "the boss fight finally started"),
        _seg(2.0, 4.0, "WAIT NO WAY, INSANE CLUTCH!!"),
        _seg(10.0, 12.0, "we kept walking"),
        _seg(20.0, 22.0, "still walking, nothing much happening"),
    ]
    moments = [
        _make_moment("strong", 0.0, 4.0, "clutch", score=3.0, energy_z=2.5, start_idx=0, end_idx=1, text="WAIT NO WAY, INSANE CLUTCH!!"),
        _make_moment("weak1", 10.0, 12.0, "reaction", score=0.2, energy_z=0.1, start_idx=2, end_idx=2, text="we kept walking"),
        _make_moment("weak2", 20.0, 22.0, "reaction", score=0.1, energy_z=0.0, start_idx=3, end_idx=3, text="still walking, nothing much happening"),
    ]
    bounds = resolve_bounds(DurationPreset.CUSTOM, custom_min=1.0, custom_max=10.0, custom_preferred=4.0)
    result = select_clips(moments, segments, _loud_profile_2_to_4(), bounds, requested_count=3)

    assert len(result.clips) == 1
    assert result.clips[0].id == "strong"
    assert result.message is not None
    assert "1" in result.message


def test_select_clips_deduplicates_heavy_overlap():
    """Two candidates covering almost the same time range should not both
    be selected -- only the higher-scoring one survives."""
    segments = [
        _seg(0.0, 2.0, "setup"),
        _seg(2.0, 4.0, "WAIT NO WAY, INSANE!!"),
        _seg(4.0, 5.0, "aftermath"),
    ]
    moments = [
        _make_moment("a", 0.0, 5.0, "clutch", score=3.0, energy_z=2.5, start_idx=0, end_idx=2),
        _make_moment("b", 1.5, 4.5, "surprise", score=2.5, energy_z=2.0, start_idx=0, end_idx=2),
    ]
    bounds = resolve_bounds(DurationPreset.CUSTOM, custom_min=1.0, custom_max=10.0, custom_preferred=5.0)
    result = select_clips(moments, segments, _loud_profile_2_to_4(), bounds, requested_count=2)
    assert len(result.clips) == 1
    assert result.clips[0].id == "a"  # higher score wins


def test_select_clips_keeps_genuinely_distinct_moments():
    """Two candidates far apart in time (no overlap) should both survive,
    even in the same category."""
    segments = [
        _seg(0.0, 2.0, "setup one"),
        _seg(2.0, 4.0, "WAIT NO WAY, INSANE!!"),
        _seg(60.0, 62.0, "setup two"),
        _seg(62.0, 64.0, "CLUTCH AGAIN, UNREAL!!"),
    ]
    moments = [
        _make_moment("a", 0.0, 4.0, "clutch", score=3.0, energy_z=2.5, start_idx=0, end_idx=1),
        _make_moment("b", 60.0, 64.0, "clutch", score=2.8, energy_z=2.3, start_idx=2, end_idx=3),
    ]
    bounds = resolve_bounds(DurationPreset.CUSTOM, custom_min=1.0, custom_max=10.0, custom_preferred=4.0)
    profile = EnergyProfile(
        window_seconds=0.5,
        rms=np.array([0.05] * 4 + [1.0] * 4 + [0.05] * 104 + [1.0] * 4),
        rms_db=np.zeros(116),
        mean_rms=0.1, std_rms=0.3,
    )
    result = select_clips(moments, segments, profile, bounds, requested_count=2)
    assert {c.id for c in result.clips} == {"a", "b"}
    assert result.message is None


def test_select_clips_category_diversity_backfills_when_needed():
    """3 strong same-category candidates, count=3: diversity caps at 2
    preferred, but with no other category available it must still
    backfill the 3rd rather than under-deliver."""
    segments = [
        _seg(0.0, 2.0, "a"), _seg(2.0, 4.0, "WAIT NO WAY!!"),
        _seg(20.0, 22.0, "b"), _seg(22.0, 24.0, "CLUTCH AGAIN!!"),
        _seg(40.0, 42.0, "c"), _seg(42.0, 44.0, "INSANE ONCE MORE!!"),
    ]
    moments = [
        _make_moment("a", 0.0, 4.0, "clutch", score=3.0, energy_z=2.5, start_idx=0, end_idx=1),
        _make_moment("b", 20.0, 24.0, "clutch", score=2.8, energy_z=2.3, start_idx=2, end_idx=3),
        _make_moment("c", 40.0, 44.0, "clutch", score=2.6, energy_z=2.1, start_idx=4, end_idx=5),
    ]
    bounds = resolve_bounds(DurationPreset.CUSTOM, custom_min=1.0, custom_max=10.0, custom_preferred=4.0)
    profile = EnergyProfile(
        window_seconds=0.5,
        rms=np.array(([0.05] * 4 + [1.0] * 4) * 3 + [0.05] * 68),
        rms_db=np.zeros(92),
        mean_rms=0.1, std_rms=0.3,
    )
    result = select_clips(moments, segments, profile, bounds, requested_count=3)
    assert len(result.clips) == 3  # all three, since no other category exists to diversify into
