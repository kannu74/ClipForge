from pathlib import Path

import app.transcription as transcription_module
from app.transcription import Segment, TranscriptResult


class ExcitingFakeEngine:
    def transcribe(self, audio_path: Path, model_size: str) -> TranscriptResult:
        return TranscriptResult(
            language="en",
            model_size=model_size,
            segments=[
                Segment(id=0, start=0.0, end=1.5, text="okay we're just chilling here"),
                Segment(id=1, start=1.5, end=3.0, text="WAIT NO WAY! ARE YOU SERIOUS?! CLUTCH!!"),
                Segment(id=2, start=3.0, end=4.5, text="that was insane, let's go again"),
            ],
        )


def _setup_project_with_moments(client, sample_video, monkeypatch):
    monkeypatch.setattr(transcription_module, "FasterWhisperEngine", ExcitingFakeEngine)
    create = client.post("/api/projects", json={"name": "Clips Router Test", "content_type": "gaming"})
    project_id = create.json()["id"]
    with sample_video.open("rb") as f:
        client.post(f"/api/projects/{project_id}/upload", files={"file": ("sample.mp4", f, "video/mp4")})
    client.post(f"/api/projects/{project_id}/transcribe")
    client.post(f"/api/projects/{project_id}/detect-moments")
    return project_id


def test_generate_clips_end_to_end(client, sample_video, monkeypatch):
    project_id = _setup_project_with_moments(client, sample_video, monkeypatch)

    resp = client.post(
        f"/api/projects/{project_id}/generate-clips",
        json={"count": 3, "duration_preset": "ultra_short"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["duration_preset"] == "ultra_short"
    assert body["requested_count"] == 3
    assert body["considered_count"] >= 1
    # This fixture's audio is a flat sine tone (no real energy spikes), so
    # only the text signal carries the score -- either we get the strong
    # clip or an honest "not enough strong candidates" message. Both are
    # correct behavior; a silent empty-with-no-message result would be a bug.
    assert len(body["clips"]) > 0 or body["message"] is not None

    if body["clips"]:
        clip = body["clips"][0]
        assert "sub_scores" in clip
        assert set(clip["sub_scores"].keys()) == {"energy", "text", "hook", "payoff", "standalone", "duration_fit"}
        assert clip["duration_explanation"].startswith("Recommended duration:")

    project = client.get(f"/api/projects/{project_id}").json()
    assert project["has_clips"] is True

    get_resp = client.get(f"/api/projects/{project_id}/clips")
    assert get_resp.status_code == 200
    assert get_resp.json()["clips"] == body["clips"]

    from app import storage
    scratch = storage.project_dir(project_id) / "clips" / "_audio.wav"
    assert not scratch.exists()


def test_generate_clips_requires_moments_first(client, sample_video, monkeypatch):
    monkeypatch.setattr(transcription_module, "FasterWhisperEngine", ExcitingFakeEngine)
    create = client.post("/api/projects", json={"name": "No Moments", "content_type": "gaming"})
    project_id = create.json()["id"]
    with sample_video.open("rb") as f:
        client.post(f"/api/projects/{project_id}/upload", files={"file": ("sample.mp4", f, "video/mp4")})
    client.post(f"/api/projects/{project_id}/transcribe")

    resp = client.post(f"/api/projects/{project_id}/generate-clips", json={"count": 3})
    assert resp.status_code == 400
    assert "moment" in resp.json()["error"].lower()


def test_generate_clips_rejects_bad_preset(client, sample_video, monkeypatch):
    project_id = _setup_project_with_moments(client, sample_video, monkeypatch)
    resp = client.post(
        f"/api/projects/{project_id}/generate-clips",
        json={"count": 2, "duration_preset": "gigantic"},
    )
    assert resp.status_code == 400


def test_generate_clips_custom_preset_requires_bounds(client, sample_video, monkeypatch):
    project_id = _setup_project_with_moments(client, sample_video, monkeypatch)
    resp = client.post(
        f"/api/projects/{project_id}/generate-clips",
        json={"count": 2, "duration_preset": "custom"},
    )
    assert resp.status_code == 400


def test_clips_404_before_generation(client, sample_video, monkeypatch):
    project_id = _setup_project_with_moments(client, sample_video, monkeypatch)
    resp = client.get(f"/api/projects/{project_id}/clips")
    assert resp.status_code == 404
