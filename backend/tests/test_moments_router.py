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


def _setup_project_with_transcript(client, sample_video, monkeypatch):
    monkeypatch.setattr(transcription_module, "FasterWhisperEngine", ExcitingFakeEngine)
    create = client.post("/api/projects", json={"name": "Moments Router Test", "content_type": "gaming"})
    project_id = create.json()["id"]
    with sample_video.open("rb") as f:
        client.post(f"/api/projects/{project_id}/upload", files={"file": ("sample.mp4", f, "video/mp4")})
    client.post(f"/api/projects/{project_id}/transcribe")
    return project_id


def test_detect_moments_end_to_end(client, sample_video, monkeypatch):
    project_id = _setup_project_with_transcript(client, sample_video, monkeypatch)

    resp = client.post(f"/api/projects/{project_id}/detect-moments")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["content_type"] == "gaming"
    assert isinstance(body["ollama_used"], bool)
    assert len(body["moments"]) >= 1
    top = body["moments"][0]
    assert top["category"] in {"clutch", "surprise", "reaction"}
    assert "CLUTCH" in top["transcript_excerpt"] or "NO WAY" in top["transcript_excerpt"]

    project = client.get(f"/api/projects/{project_id}").json()
    assert project["has_moments"] is True
    assert project["status"] == "ready"

    get_resp = client.get(f"/api/projects/{project_id}/moments")
    assert get_resp.status_code == 200
    assert get_resp.json()["moments"][0]["id"] == top["id"]

    # Scratch audio used for energy analysis is cleaned up.
    from app import storage
    scratch = storage.project_dir(project_id) / "moments" / "_audio.wav"
    assert not scratch.exists()


def test_detect_moments_requires_transcript_first(client, sample_video):
    create = client.post("/api/projects", json={"name": "No Transcript", "content_type": "gaming"})
    project_id = create.json()["id"]
    with sample_video.open("rb") as f:
        client.post(f"/api/projects/{project_id}/upload", files={"file": ("sample.mp4", f, "video/mp4")})
    resp = client.post(f"/api/projects/{project_id}/detect-moments")
    assert resp.status_code == 400
    assert "transcript" in resp.json()["error"].lower()


def test_moments_404_before_detection(client, sample_video, monkeypatch):
    project_id = _setup_project_with_transcript(client, sample_video, monkeypatch)
    resp = client.get(f"/api/projects/{project_id}/moments")
    assert resp.status_code == 404
