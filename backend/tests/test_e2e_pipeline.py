"""
End-to-end: upload a real (synthetic) gaming-style video with a facecam in
the corner and a loud reaction section -> background "process" job
(transcribe with an injected engine, detect, rank) -> background renders ->
real MP4s with burned-in captions, split facecam layout, thumbnails, SRT
and QC. Only speech recognition is faked (the model can't be downloaded in
CI); everything else -- ffmpeg, face detection, captions, jobs -- is real.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

import app.transcription as transcription_module
from app import jobs, media
from app.transcription import Segment, TranscriptResult, Word

ASSETS = Path(__file__).parent / "assets"


def _words(text: str, start: float, end: float) -> list[Word]:
    toks = text.split()
    step = (end - start) / len(toks)
    return [Word(word=t, start=round(start + i * step, 2), end=round(start + (i + 0.9) * step, 2)) for i, t in enumerate(toks)]


SCRIPT = [
    (0.5, 3.5, "okay guys aaj hum ye horror game khel rahe hain"),
    (3.8, 7.5, "bhai ye jagah bahut creepy lag rahi hai honestly"),
    (7.8, 9.8, "wait did you hear that sound?"),
    (10.2, 13.0, "BHAI BHOOT! NO WAY! RUN RUN RUN!!"),
    (13.2, 15.8, "ye kya tha yaar I literally screamed!"),
    (16.2, 19.5, "okay okay let's calm down and keep exploring"),
    (19.8, 23.5, "so this door leads to the basement I think"),
    (23.8, 27.5, "no no no I'm not going down there bro"),
]


class ScriptedEngine:
    def transcribe(self, audio_path: Path, model_size: str, language=None, on_progress=None) -> TranscriptResult:
        segs = []
        for i, (s, e, text) in enumerate(SCRIPT):
            segs.append(Segment(id=i, start=s, end=e, text=text, words=_words(text, s, e)))
            if on_progress:
                on_progress((i + 1) / len(SCRIPT), "transcribing")
        return TranscriptResult(language="hi", model_size=model_size, segments=segs)


@pytest.fixture(scope="module")
def gaming_video() -> Path:
    d = Path(tempfile.mkdtemp(prefix="clipforge_e2e_"))
    out = d / "gaming.mp4"
    # 30s 1280x720 "gameplay" with a facecam (real face photo) bottom-right,
    # audio quiet except a loud reaction at 10-16s.
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=30",
            "-loop", "1", "-i", str(ASSETS / "face.jpg"),
            "-f", "lavfi", "-i", "sine=frequency=330:duration=30:sample_rate=44100",
            "-filter_complex",
            "[1:v]scale=220:220[cam];[0:v][cam]overlay=W-240:H-240:shortest=1[v];"
            "[2:a]volume='if(between(t,10,16),1.0,0.05)':eval=frame[a]",
            "-map", "[v]", "-map", "[a]", "-t", "30",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(out),
        ],
        capture_output=True, check=True, timeout=120,
    )
    return out


def test_full_pipeline_renders_real_clips(client, gaming_video, monkeypatch):
    monkeypatch.setattr(transcription_module, "FasterWhisperEngine", ScriptedEngine)

    create = client.post(
        "/api/projects",
        json={
            "name": "E2E horror",
            "content_type": "horror_gaming",
            "settings": {
                "clip_count": 2,
                "duration_preset": "custom",
                "custom_min_seconds": 6,
                "custom_max_seconds": 14,
                "captions": {"style": "bold_pop", "script": "as_spoken"},
                "render": {"resolution": 720, "quality": "fast"},
            },
        },
    )
    assert create.status_code == 201, create.text
    pid = create.json()["id"]
    assert create.json()["settings"]["clip_count"] == 2

    with gaming_video.open("rb") as f:
        up = client.post(f"/api/projects/{pid}/upload", files={"file": ("gaming.mp4", f, "video/mp4")})
    assert up.status_code == 200, up.text

    job = client.post(f"/api/projects/{pid}/process", json={}).json()
    assert job["kind"] == "process"
    assert jobs.wait_idle(timeout=300), "jobs did not finish"

    done = client.get(f"/api/jobs/{job['id']}").json()
    assert done["status"] == "done", done

    clips = client.get(f"/api/projects/{pid}/clips").json()
    assert clips["clips"], clips
    top = clips["clips"][0]
    # The loud, exclamation-heavy reaction (10-16s) must be inside the top clip.
    assert top["start"] <= 10.5 and top["end"] >= 13.0, top
    assert 6 <= top["end"] - top["start"] <= 16.5
    assert top["title"]
    assert 1 <= top["virality"] <= 99

    for c in clips["clips"]:
        r = c["render"]
        assert r["status"] == "done", r
        assert r["width"] == 720 and r["height"] == 1280
        assert r["qc"]["passed"], r["qc"]
        # The facecam in the corner should trigger the split layout.
        assert r["reframe_mode"] == "split", r
        assert r["stale"] is False

        vid = client.get(f"/api/projects/{pid}/clips/{c['id']}/video")
        assert vid.status_code == 200 and len(vid.content) > 10_000
        ranged = client.get(f"/api/projects/{pid}/clips/{c['id']}/video", headers={"Range": "bytes=0-99"})
        assert ranged.status_code == 206 and len(ranged.content) == 100
        thumb = client.get(f"/api/projects/{pid}/clips/{c['id']}/thumbnail")
        assert thumb.status_code == 200 and thumb.content[:2] == b"\xff\xd8"
        srt = client.get(f"/api/projects/{pid}/clips/{c['id']}/srt")
        assert srt.status_code == 200 and "-->" in srt.text

    # Rendered file really is a playable 9:16 H.264 video with audio.
    from app import storage

    mp4 = storage.renders_dir(pid) / top["render"]["file"]
    meta = media.probe(mp4)
    assert (meta.width, meta.height) == (720, 1280)
    assert meta.video_codec == "h264" and meta.has_audio
    assert abs(meta.duration_seconds - (top["end"] - top["start"])) < 0.6

    # Editing the clip marks it stale, re-render clears it.
    patch = client.patch(
        f"/api/projects/{pid}/clips/{top['id']}",
        json={"start": top["start"] + 1.0, "caption_overrides": {"style": "karaoke"}},
    )
    assert patch.status_code == 200, patch.text
    listed = client.get(f"/api/projects/{pid}/clips").json()
    edited = next(c for c in listed["clips"] if c["id"] == top["id"])
    assert edited["render"]["stale"] is True
    client.post(f"/api/projects/{pid}/clips/{top['id']}/render")
    assert jobs.wait_idle(timeout=180)
    listed = client.get(f"/api/projects/{pid}/clips").json()
    edited = next(c for c in listed["clips"] if c["id"] == top["id"])
    assert edited["render"]["status"] == "done" and edited["render"]["stale"] is False

    # Manual clip + caption text edit + zip of everything.
    manual = client.post(f"/api/projects/{pid}/clips", json={"start": 20, "end": 27, "title": "Basement nope", "render": True})
    assert manual.status_code == 201, manual.text
    mid = manual.json()["id"]
    words = client.get(f"/api/projects/{pid}/clips/{mid}/words").json()["words"]
    assert words and words[0]["start"] >= 19.5
    words[0]["word"] = "SO"
    put = client.put(f"/api/projects/{pid}/clips/{mid}/words", json={"words": words, "render": True})
    assert put.status_code == 200 and put.json()["edited"] is True
    assert jobs.wait_idle(timeout=180)
    z = client.get(f"/api/projects/{pid}/clips.zip")
    assert z.status_code == 200 and z.content[:2] == b"PK"

    # Rerank with a different count reuses the transcript.
    client.patch(f"/api/projects/{pid}/settings", json={"clip_count": 1, "auto_render": False})
    rr = client.post(f"/api/projects/{pid}/rerank").json()
    assert rr["kind"] == "rerank"
    assert jobs.wait_idle(timeout=120)
    after = client.get(f"/api/projects/{pid}/clips").json()
    autos = [c for c in after["clips"] if c["origin"] == "auto"]
    manuals = [c for c in after["clips"] if c["origin"] == "manual"]
    assert len(autos) == 1 and len(manuals) == 1


def test_process_requires_a_source(client):
    pid = client.post("/api/projects", json={"name": "empty"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/process", json={})
    assert r.status_code == 400
    assert "video" in r.json()["error"].lower()


def test_process_rejects_bad_youtube_url(client):
    pid = client.post("/api/projects", json={"name": "yt"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/process", json={"youtube_url": "https://example.com/x"})
    assert r.status_code == 400


def test_settings_validation(client):
    pid = client.post("/api/projects", json={"name": "s"}).json()["id"]
    ok = client.patch(f"/api/projects/{pid}/settings", json={"captions": {"highlight_color": "#00ff00"}})
    assert ok.status_code == 200 and ok.json()["captions"]["highlight_color"] == "#00FF00"
    bad = client.patch(f"/api/projects/{pid}/settings", json={"captions": {"style": "comic-sans"}})
    assert bad.status_code == 400
