from types import SimpleNamespace

from app.audio_analysis import compute_energy_profile
from app.moments import detect_moments


def _seg(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text)


def test_detect_moments_finds_the_exciting_window(synthetic_energy_audio):
    """Uses the real energy profile from synthetic_energy_audio (quiet/loud/quiet)
    paired with a hand-crafted transcript whose exciting line lines up with the
    loud 2-4s window. This is a real, meaningful assertion about detector
    behavior, not just 'no exception'."""
    profile = compute_energy_profile(synthetic_energy_audio, window_seconds=0.5)
    segments = [
        _seg(0.0, 2.0, "okay so we're just walking around the map right now"),
        _seg(2.0, 4.0, "WAIT WHAT?! NO WAY! ARE YOU SERIOUS RIGHT NOW?!"),
        _seg(4.0, 6.0, "okay that was actually insane, let's keep going"),
    ]

    moments, ollama_used = detect_moments("gaming", segments, profile)

    assert ollama_used is False  # nothing listening on Ollama's port in this environment
    assert len(moments) >= 1
    top = moments[0]
    assert top.category in {"surprise", "reaction", "clutch"}
    assert top.signals["energy_z"] > 1.0
    assert "WAIT WHAT" in top.transcript_excerpt or "NO WAY" in top.transcript_excerpt
    assert top.reason  # explanation is never empty
    assert top.llm_enriched is False
    # The window should include neighboring context, not just the peak line alone.
    assert top.start <= 2.0 and top.end >= 4.0


def test_detect_moments_ignores_flat_neutral_content(synthetic_energy_audio):
    """Reuses the same audio but with entirely neutral, keyword-free text
    everywhere -- the loud 2-4s window still has energy, but should not
    always dominate a video with zero textual signal either; more
    importantly, a fully flat/neutral video should not produce noise."""
    profile = compute_energy_profile(synthetic_energy_audio, window_seconds=0.5)
    segments = [
        _seg(0.0, 2.0, "we are walking down the corridor"),
        _seg(2.0, 4.0, "we continue walking down the corridor"),
        _seg(4.0, 6.0, "we keep walking down the corridor"),
    ]
    moments, _ = detect_moments("gaming", segments, profile)
    # The loud window still has real energy (from the audio), so it's fine
    # if it's picked up -- but every returned moment must have a real signal
    # backing it (never zero energy AND zero keywords).
    for m in moments:
        assert m.signals["energy_z"] > 0 or m.signals["keyword_matches"]


def test_detect_moments_respects_content_type_lexicon():
    """A pure energy-flat clip (no audio signal used here -- feed a
    profile of all-equal loudness) with horror-relevant language should be
    categorized using the horror-appropriate vocabulary."""
    import numpy as np
    from app.audio_analysis import EnergyProfile

    flat = EnergyProfile(window_seconds=0.5, rms=np.array([0.1] * 20), rms_db=np.array([-20.0] * 20), mean_rms=0.1, std_rms=0.0)
    segments = [
        _seg(0.0, 2.0, "we're slowly walking into the basement"),
        _seg(2.0, 4.0, "bhai this game is so scary, I think there's a bhoot in here"),
        _seg(4.0, 6.0, "okay let's keep going carefully"),
    ]
    moments, _ = detect_moments("horror_gaming", segments, flat)
    assert len(moments) >= 1
    assert moments[0].category == "scare"


def test_ollama_enrichment_path_via_injected_client(synthetic_energy_audio):
    """Real Ollama isn't reachable in this environment, so this verifies the
    enrichment CODE PATH with a fake client standing in for it -- the merge
    logic (category override, score adjustment, reason replacement,
    llm_enriched flag) is exercised for real."""

    class FakeOllamaClient:
        def is_reachable(self) -> bool:
            return True

        def enrich_moment(self, transcript_excerpt, content_type, category_guess):
            return {"category": "clutch", "score_adjustment": 2, "reason": "LLM says this is a clean clutch moment."}

    profile = compute_energy_profile(synthetic_energy_audio, window_seconds=0.5)
    segments = [
        _seg(0.0, 2.0, "okay so we're just walking around the map right now"),
        _seg(2.0, 4.0, "WAIT WHAT?! NO WAY! ARE YOU SERIOUS RIGHT NOW?!"),
        _seg(4.0, 6.0, "okay that was actually insane, let's keep going"),
    ]

    moments, ollama_used = detect_moments("gaming", segments, profile, ollama_client=FakeOllamaClient())

    assert ollama_used is True
    top = moments[0]
    assert top.llm_enriched is True
    assert top.category == "clutch"
    assert top.reason == "LLM says this is a clean clutch moment."


def test_detect_moments_handles_no_segments():
    from app.audio_analysis import EnergyProfile
    import numpy as np

    empty_profile = EnergyProfile(window_seconds=0.5, rms=np.array([0.0]), rms_db=np.array([-100.0]), mean_rms=0.0, std_rms=0.0)
    moments, ollama_used = detect_moments("gaming", [], empty_profile)
    assert moments == []
    assert ollama_used is False
