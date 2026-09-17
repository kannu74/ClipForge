from pathlib import Path

import app.transcription as transcription_module
from app.transcription import Segment, TranscriptResult, Word


class FakeEngine:
    """Stands in for FasterWhisperEngine so orchestration (file handling,
    JSON I/O, API contract, manual-edit flow) can be verified without a
    downloaded model. Real ASR quality is NOT covered by this fake --
    see DEVELOPMENT_PROGRESS.md for what still needs real-world verification."""

    def transcribe(self, audio_path: Path, model_size: str) -> TranscriptResult:
        assert audio_path.exists(), "engine should receive a real extracted audio file"
        assert audio_path.stat().st_size > 0
        return TranscriptResult(
            language="en",
            model_size=model_size,
            segments=[
                Segment(
                    id=0,
                    start=0.0,
                    end=2.0,
                    text="bhai ye kya ho raha hai",
                    words=[
                        Word(word="bhai", start=0.0, end=0.4),
                        Word(word="ye", start=0.4, end=0.6),
                        Word(word="kya", start=0.6, end=0.9),
                        Word(word="ho", start=0.9, end=1.1),
                        Word(word="raha", start=1.1, end=1.4),
                        Word(word="hai", start=1.4, end=1.8),
                    ],
                ),
                Segment(id=1, start=2.0, end=4.0, text="what the hell just happened"),
            ],
        )


def _patch_engine(monkeypatch):
    monkeypatch.setattr(transcription_module, "FasterWhisperEngine", FakeEngine)


def test_transcribe_end_to_end_with_fake_engine(client, sample_video, monkeypatch):
    _patch_engine(monkeypatch)

    create = client.post("/api/projects", json={"name": "Transcribe Test", "content_type": "gaming"})
    project_id = create.json()["id"]
    with sample_video.open("rb") as f:
        client.post(f"/api/projects/{project_id}/upload", files={"file": ("sample.mp4", f, "video/mp4")})

    resp = client.post(f"/api/projects/{project_id}/transcribe")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["language"] == "en"
    assert len(body["segments"]) == 2
    # Hinglish text preserved verbatim -- NOT translated to English.
    assert body["segments"][0]["text"] == "bhai ye kya ho raha hai"
    assert len(body["segments"][0]["words"]) == 6
    assert body["segments"][0]["words"][0]["word"] == "bhai"

    # Project reflects has_transcript now.
    project = client.get(f"/api/projects/{project_id}").json()
    assert project["has_transcript"] is True
    assert project["status"] == "ready"

    # GET transcript returns the same data.
    get_resp = client.get(f"/api/projects/{project_id}/transcript")
    assert get_resp.status_code == 200
    assert get_resp.json()["segments"][0]["text"] == "bhai ye kya ho raha hai"

    # The scratch audio file used for transcription is cleaned up afterward.
    from app import storage
    audio_scratch = storage.project_dir(project_id) / "transcript" / "_audio.wav"
    assert not audio_scratch.exists()


def test_edit_segment(client, sample_video, monkeypatch):
    _patch_engine(monkeypatch)
    create = client.post("/api/projects", json={"name": "Edit Test", "content_type": "gaming"})
    project_id = create.json()["id"]
    with sample_video.open("rb") as f:
        client.post(f"/api/projects/{project_id}/upload", files={"file": ("sample.mp4", f, "video/mp4")})
    client.post(f"/api/projects/{project_id}/transcribe")

    resp = client.patch(
        f"/api/projects/{project_id}/transcript/segments/0",
        json={"text": "bhai ye kya ho gaya"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["segments"][0]["text"] == "bhai ye kya ho gaya"
    assert body["segments"][0]["edited"] is True
    # Untouched segment is unaffected.
    assert body["segments"][1]["edited"] is False


def test_transcribe_without_source_gives_friendly_error(client):
    create = client.post("/api/projects", json={"name": "No Source", "content_type": "gaming"})
    project_id = create.json()["id"]
    resp = client.post(f"/api/projects/{project_id}/transcribe")
    assert resp.status_code == 400
    assert "video" in resp.json()["error"].lower()


def test_transcript_404_before_transcribing(client, sample_video):
    create = client.post("/api/projects", json={"name": "Pre Transcript", "content_type": "gaming"})
    project_id = create.json()["id"]
    with sample_video.open("rb") as f:
        client.post(f"/api/projects/{project_id}/upload", files={"file": ("sample.mp4", f, "video/mp4")})
    resp = client.get(f"/api/projects/{project_id}/transcript")
    assert resp.status_code == 404


def test_real_engine_fails_gracefully_without_model_access(client, sample_video):
    """No network to huggingface.co in this sandbox -- the REAL engine should
    surface a plain-language error (via ClipForgeError), not a raw traceback
    or a bare 500. This is exactly the error-handling behavior CLAUDE.md
    requires (never a raw 'CUDA error' / stack-trace-style message)."""
    create = client.post("/api/projects", json={"name": "Real Engine Test", "content_type": "gaming"})
    project_id = create.json()["id"]
    with sample_video.open("rb") as f:
        client.post(f"/api/projects/{project_id}/upload", files={"file": ("sample.mp4", f, "video/mp4")})

    resp = client.post(f"/api/projects/{project_id}/transcribe?model_size=tiny")
    assert resp.status_code in (503, 507), resp.text
    body = resp.json()
    assert "error" in body
    assert "traceback" not in body["error"].lower()
    assert "cuda" not in body["error"].lower()  # plain language, not a raw technical error
