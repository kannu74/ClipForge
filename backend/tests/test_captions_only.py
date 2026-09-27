from __future__ import annotations

from app import jobs, media
import app.reframe as reframe_module
import app.transcription as transcription_module
from tests.test_e2e_pipeline import ScriptedEngine


def test_caption_only_processes_one_full_source_without_framing(client, sample_video, monkeypatch):
    monkeypatch.setattr(transcription_module, "FasterWhisperEngine", ScriptedEngine)

    def fail_face_analysis(*args, **kwargs):
        raise AssertionError("caption-only rendering must not run face analysis")

    monkeypatch.setattr(reframe_module, "analyze", fail_face_analysis)
    created = client.post(
        "/api/projects",
        json={
            "name": "Caption only",
            "content_type": "general_creator",
            "settings": {
                "workflow_mode": "captions_only",
                "auto_render": True,
                "render": {"output_mode": "source", "quality": "fast"},
            },
        },
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    with sample_video.open("rb") as source:
        uploaded = client.post(
            f"/api/projects/{project_id}/upload",
            files={"file": ("source.mp4", source, "video/mp4")},
        )
    assert uploaded.status_code == 200, uploaded.text

    job = client.post(f"/api/projects/{project_id}/process", json={}).json()
    assert jobs.wait_idle(timeout=180)
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "done"

    result = client.get(f"/api/projects/{project_id}/clips").json()
    assert len(result["clips"]) == 1
    target = result["clips"][0]
    assert target["origin"] == "captions_only"
    assert target["start"] == 0
    assert target["end"] == client.get(f"/api/projects/{project_id}").json()["metadata"]["duration_seconds"]
    assert target["render"]["status"] == "done"
    assert target["render"]["reframe_mode"] == "original"
    assert target["render"]["width"] == client.get(f"/api/projects/{project_id}").json()["metadata"]["width"]
    assert target["render"]["height"] == client.get(f"/api/projects/{project_id}").json()["metadata"]["height"]

    video = client.get(f"/api/projects/{project_id}/clips/{target['id']}/video")
    assert video.status_code == 200 and len(video.content) > 10_000
    srt = client.get(f"/api/projects/{project_id}/clips/{target['id']}/srt")
    assert srt.status_code == 200 and "-->" in srt.text

    words = client.get(f"/api/projects/{project_id}/clips/{target['id']}/words").json()["words"]
    assert words
    words[0]["word"] = "EDITED"
    assert client.put(
        f"/api/projects/{project_id}/clips/{target['id']}/words",
        json={"words": words, "render": True},
    ).status_code == 200
    assert jobs.wait_idle(timeout=180)
    updated = client.get(f"/api/projects/{project_id}/clips").json()["clips"][0]
    assert updated["render"]["status"] == "done"

    rendered = client.get(f"/api/projects/{project_id}/clips/{target['id']}/video")
    assert rendered.status_code == 200
    assert media.probe is not None
