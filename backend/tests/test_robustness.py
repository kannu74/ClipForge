"""Regression tests for problems found in review: no-audio sources, state
left behind by interrupted/cancelled jobs, extending a clip whose caption
text was edited, and a cancel reaching the YouTube downloader."""
from __future__ import annotations

import subprocess
from pathlib import Path

import app.transcription as transcription_module
from app import clip_store, jobs, pipeline
from tests.test_e2e_pipeline import ScriptedEngine


def _upload(client, path: Path, name="v.mp4", settings=None) -> str:
    pid = client.post("/api/projects", json={"name": "r", "settings": settings or {"auto_render": False}}).json()["id"]
    with path.open("rb") as f:
        assert client.post(f"/api/projects/{pid}/upload", files={"file": (name, f, "video/mp4")}).status_code == 200
    return pid


def test_video_without_audio_explains_and_stays_usable(client, tmp_path):
    silent = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=4", "-c:v", "libx264", str(silent)],
        capture_output=True, check=True, timeout=60,
    )
    pid = _upload(client, silent)
    job = client.post(f"/api/projects/{pid}/process", json={}).json()
    assert jobs.wait_idle(60)
    done = client.get(f"/api/jobs/{job['id']}").json()
    assert done["status"] == "failed"
    assert "no audio" in done["error"].lower()
    assert "Cut a clip yourself" in done["suggestion"]
    assert client.get(f"/api/projects/{pid}").json()["status"] == "ready"
    # Manual clips still work.
    r = client.post(f"/api/projects/{pid}/clips", json={"start": 0.5, "end": 3.0, "render": True})
    assert r.status_code == 201
    assert jobs.wait_idle(60)
    clips = client.get(f"/api/projects/{pid}/clips").json()["clips"]
    assert clips[0]["render"]["status"] == "done"


def test_interrupted_render_is_reset_after_restart(client, sample_video, monkeypatch):
    monkeypatch.setattr(transcription_module, "FasterWhisperEngine", ScriptedEngine)
    pid = _upload(client, sample_video)
    clip = clip_store.add_manual_clip(pid, 0.5, 3.0, "x", "", "gaming")
    clip_store.update_clip(pid, clip["id"], {"render": {"status": "rendering"}})
    pipeline.recover_interrupted([{"id": "j", "kind": "render", "project_id": pid, "params": {"clip_id": clip["id"]}}])
    assert clip_store.get_clip(pid, clip["id"])["render"]["status"] == "none"


def test_cancelling_a_queued_render_clears_its_badge(client, sample_video):
    pid = _upload(client, sample_video)
    clip = clip_store.add_manual_clip(pid, 0.5, 3.0, "x", "", "gaming")
    jobs.stop_workers()  # keep the job queued
    try:
        job = pipeline.enqueue_render(pid, clip["id"])
        assert clip_store.get_clip(pid, clip["id"])["render"]["status"] == "queued"
        jobs.request_cancel(job["id"])
        assert jobs.get_job(job["id"])["status"] == "cancelled"
        assert clip_store.get_clip(pid, clip["id"])["render"]["status"] == "none"
    finally:
        jobs.start_workers()


def test_extending_a_clip_with_edited_captions_fills_new_words(client, monkeypatch, tmp_path):
    monkeypatch.setattr(transcription_module, "FasterWhisperEngine", ScriptedEngine)
    video = tmp_path / "talk.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=30",
         "-f", "lavfi", "-i", "sine=duration=30", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(video)],
        capture_output=True, check=True, timeout=60,
    )
    pid = _upload(client, video)
    client.post(f"/api/projects/{pid}/transcribe")
    clip = client.post(f"/api/projects/{pid}/clips", json={"start": 10.0, "end": 13.1, "render": False}).json()
    words = client.get(f"/api/projects/{pid}/clips/{clip['id']}/words").json()["words"]
    words[0]["word"] = "EDITED"
    client.put(f"/api/projects/{pid}/clips/{clip['id']}/words", json={"words": words})
    client.patch(f"/api/projects/{pid}/clips/{clip['id']}", json={"start": 7.5, "end": 16.0})
    after = client.get(f"/api/projects/{pid}/clips/{clip['id']}/words").json()["words"]
    texts = [w["word"] for w in after]
    assert "EDITED" in texts  # the edit survived
    assert after[0]["start"] < 10.0 and after[-1]["end"] > 13.2  # new stretches got captions
    assert texts[:2] == ["wait", "did"]


def test_cancel_propagates_through_youtube_progress_hook():
    # JobCancelled must not be an Exception, or yt-dlp's generic handlers
    # (and ours) would swallow it and report "download failed".
    assert not issubclass(jobs.JobCancelled, Exception)
