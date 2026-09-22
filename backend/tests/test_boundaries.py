from types import SimpleNamespace

import numpy as np

from app.audio_analysis import EnergyProfile
from app.boundaries import refine_boundaries
from app.duration_presets import DurationPreset, resolve_bounds


def _seg(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text)


def _energy_profile_loud_from_2_to_5s() -> EnergyProfile:
    # 14 windows of 0.5s = 7.0s total. Loud (z >> 1) from 2.0s-5.0s, quiet elsewhere.
    rms = np.array([0.05] * 4 + [1.0] * 6 + [0.05] * 4)
    return EnergyProfile(
        window_seconds=0.5, rms=rms, rms_db=20 * np.log10(rms),
        mean_rms=float(np.mean(rms)), std_rms=float(np.std(rms)),
    )


SEGMENTS = [
    _seg(0.0, 0.8, "um so"),
    _seg(0.8, 2.5, "okay we're heading into the basement now"),
    _seg(2.5, 4.0, "WAIT WHAT?! NO WAY! ARE YOU SERIOUS?!"),
    _seg(4.0, 5.5, "oh my god that was terrifying"),
    _seg(5.5, 7.0, "okay let's keep moving forward"),
]


def test_trims_leading_filler_segment():
    bounds = resolve_bounds(DurationPreset.STANDARD)
    profile = _energy_profile_loud_from_2_to_5s()
    result = refine_boundaries(SEGMENTS, start_idx=0, end_idx=2, energy_profile=profile, bounds=bounds)
    assert result.trimmed_filler is True
    assert result.start_idx == 1
    assert result.start == 0.8


def test_does_not_trim_a_real_content_opener():
    bounds = resolve_bounds(DurationPreset.STANDARD)
    profile = _energy_profile_loud_from_2_to_5s()
    result = refine_boundaries(SEGMENTS, start_idx=1, end_idx=2, energy_profile=profile, bounds=bounds)
    assert result.trimmed_filler is False
    assert result.start_idx == 1


def test_extends_end_when_reaction_still_going():
    bounds = resolve_bounds(DurationPreset.STANDARD)
    profile = _energy_profile_loud_from_2_to_5s()
    # Window nominally ends at segment 2 (t=4.0), but energy is still loud
    # right up to t=5.0 and segment 3 continues the reaction with no gap.
    result = refine_boundaries(SEGMENTS, start_idx=1, end_idx=2, energy_profile=profile, bounds=bounds)
    assert result.extended_for_reaction is True
    assert result.end_idx == 3
    assert result.end == 5.5
    # Should NOT extend further into segment 4 -- energy has dropped by t=5.5.
    assert "5" in result.explanation or "6" in result.explanation  # sanity: explanation mentions a duration


def test_does_not_extend_past_max_duration_overrun_tolerance():
    # A tight custom max forces the overrun cap to kick in.
    bounds = resolve_bounds(DurationPreset.CUSTOM, custom_min=1.0, custom_max=2.0, custom_preferred=1.5)
    profile = _energy_profile_loud_from_2_to_5s()
    result = refine_boundaries(SEGMENTS, start_idx=2, end_idx=2, energy_profile=profile, bounds=bounds)
    # 2.0 * 1.15 = 2.3s max allowed overrun; segment 2 alone is already 1.5s,
    # so extending to segment 3 (would be 3.0s) must be refused.
    assert result.end_idx == 2


def test_duration_explanation_is_always_present_and_readable():
    bounds = resolve_bounds(DurationPreset.STANDARD)
    profile = _energy_profile_loud_from_2_to_5s()
    result = refine_boundaries(SEGMENTS, start_idx=1, end_idx=3, energy_profile=profile, bounds=bounds)
    assert result.explanation.startswith("Recommended duration:")
    assert len(result.explanation) > 20
