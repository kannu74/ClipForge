from app.media import probe
from app.youtube import extract_video_id
from app.errors import ValidationFailedError, UnsupportedMediaError
import pytest


# --- ffprobe / media.py, against a REAL ffmpeg-generated video ---

def test_probe_real_video_metadata(sample_video):
    meta = probe(sample_video)
    assert 4.5 <= meta.duration_seconds <= 5.5
    assert meta.width == 640
    assert meta.height == 360
    assert 29 <= meta.fps <= 31
    assert meta.video_codec == "h264"
    assert meta.audio_codec == "aac"
    assert meta.has_audio is True
    assert meta.aspect_ratio == "16:9"
    assert meta.file_size_bytes > 0


def test_probe_rejects_unsupported_extension(tmp_path):
    fake = tmp_path / "not_a_video.txt"
    fake.write_text("hello")
    with pytest.raises(UnsupportedMediaError):
        probe(fake)


def test_probe_rejects_corrupt_file(tmp_path):
    fake = tmp_path / "corrupt.mp4"
    fake.write_bytes(b"not actually a video")
    with pytest.raises(UnsupportedMediaError):
        probe(fake)


# --- YouTube URL validation (pure, no network) ---

@pytest.mark.parametrize(
    "url,expected_id",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtube.com/watch?v=dQw4w9WgXcQ&t=30s", "dQw4w9WgXcQ"),
    ],
)
def test_extract_video_id_accepts_valid_urls(url, expected_id):
    assert extract_video_id(url) == expected_id


@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "https://vimeo.com/12345",
        "https://www.youtube.com/",
        "",
    ],
)
def test_extract_video_id_rejects_invalid_urls(url):
    with pytest.raises(ValidationFailedError):
        extract_video_id(url)


# --- End-to-end upload via the real API, real video file ---

def test_upload_video_end_to_end(client, sample_video):
    create = client.post("/api/projects", json={"name": "Ingest Test", "content_type": "gaming"})
    project_id = create.json()["id"]

    with sample_video.open("rb") as f:
        resp = client.post(
            f"/api/projects/{project_id}/upload",
            files={"file": ("sample.mp4", f, "video/mp4")},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["source_type"] == "local"
    assert body["metadata"]["width"] == 640
    assert body["metadata"]["height"] == 360
    assert 4.5 <= body["metadata"]["duration_seconds"] <= 5.5

    # Media is actually retrievable and playable-sized.
    media_resp = client.get(f"/api/projects/{project_id}/media")
    assert media_resp.status_code == 200
    assert len(media_resp.content) > 1000

    # Re-fetching the project reflects the ingested state.
    get_resp = client.get(f"/api/projects/{project_id}")
    assert get_resp.json()["metadata"]["video_codec"] == "h264"


def test_upload_rejects_bad_extension(client):
    create = client.post("/api/projects", json={"name": "Bad Upload", "content_type": "comedy"})
    project_id = create.json()["id"]
    resp = client.post(
        f"/api/projects/{project_id}/upload",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_youtube_endpoint_rejects_bad_url(client):
    create = client.post("/api/projects", json={"name": "YT Test", "content_type": "gaming"})
    project_id = create.json()["id"]
    resp = client.post(f"/api/projects/{project_id}/youtube", json={"url": "not a youtube url"})
    assert resp.status_code == 400


def test_media_404_before_ingest(client):
    create = client.post("/api/projects", json={"name": "No Source Yet", "content_type": "gaming"})
    project_id = create.json()["id"]
    resp = client.get(f"/api/projects/{project_id}/media")
    assert resp.status_code == 404
