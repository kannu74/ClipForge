from app.audio_analysis import compute_energy_profile


def test_energy_profile_distinguishes_loud_from_quiet(synthetic_energy_audio):
    profile = compute_energy_profile(synthetic_energy_audio, window_seconds=0.5)

    quiet_start_z = profile.peak_z_in_range(0.0, 1.5)
    loud_z = profile.peak_z_in_range(2.25, 3.75)
    quiet_end_z = profile.peak_z_in_range(4.25, 5.75)

    assert loud_z > quiet_start_z
    assert loud_z > quiet_end_z
    # A 50x volume jump should read as a real statistical spike, not noise.
    assert loud_z > 1.0
    assert quiet_start_z < 0.5
    assert quiet_end_z < 0.5
