"""A ClipForge left running while the code is updated must not keep serving
the old code silently (first real run: renders kept failing with a bug that
was already fixed on disk, because re-launching just re-opened the browser
on the old server)."""
from __future__ import annotations

import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from app import buildinfo, clip_store, jobs, pipeline
from tests.test_robustness import _upload


def test_fingerprint_tracks_code_changes(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("x = 1\n")
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    fp1 = buildinfo.code_fingerprint(tmp_path)
    assert buildinfo.code_fingerprint(tmp_path) == fp1
    # CRLF checkout of the same code is the same build.
    (tmp_path / "app" / "a.py").write_bytes(b"x = 1\r\n")
    assert buildinfo.code_fingerprint(tmp_path) == fp1
    (tmp_path / "app" / "a.py").write_text("x = 2\n")
    assert buildinfo.code_fingerprint(tmp_path) != fp1


def test_health_reports_build_and_update_pending(client, monkeypatch):
    h = client.get("/api/system/health").json()
    assert h["status"] == "ok" and h["build"] == buildinfo.RUNNING and h["pid"] > 0
    assert h["update_pending"] is False
    monkeypatch.setattr(buildinfo, "_disk_cache", (time.time(), "something-newer"))
    assert client.get("/api/system/health").json()["update_pending"] is True


def test_renders_failed_on_older_version_are_retried_once(client, sample_video):
    pid = _upload(client, sample_video)
    old = clip_store.add_manual_clip(pid, 0.5, 3.0, "old failure", "", "gaming")
    cur = clip_store.add_manual_clip(pid, 1.0, 3.5, "current failure", "", "gaming")
    # A failure recorded before builds were stamped, and one on this build.
    clip_store.update_clip(pid, old["id"], {"render": {"status": "failed", "error": "Couldn't render this clip."}})
    clip_store.update_clip(
        pid, cur["id"], {"render": {"status": "failed", "error": "x", "build": buildinfo.RUNNING}}
    )
    assert pipeline.retry_renders_after_update() == 1
    assert jobs.wait_idle(60)
    assert clip_store.get_clip(pid, old["id"])["render"]["status"] == "done"
    assert clip_store.get_clip(pid, cur["id"])["render"]["status"] == "failed"
    assert pipeline.retry_renders_after_update() == 0


def test_render_failure_is_stamped_with_build_and_suggestion(client, sample_video, monkeypatch):
    from app import render

    pid = _upload(client, sample_video)
    clip = clip_store.add_manual_clip(pid, 0.5, 3.0, "x", "", "gaming")

    def boom(*a, **k):
        raise render.RenderFailedError("Couldn't render this clip.", suggestion="Try another style.")

    monkeypatch.setattr(render, "render_clip", boom)
    pipeline.enqueue_render(pid, clip["id"])
    assert jobs.wait_idle(60)
    r = clip_store.get_clip(pid, clip["id"])["render"]
    assert r["status"] == "failed" and r["build"] == buildinfo.RUNNING and r["suggestion"] == "Try another style."


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_launcher_stops_an_outdated_server(tmp_path):
    """run.py finds an old ClipForge (whose health has no build/pid -- like
    the version that was actually left running) by its port and stops it."""
    port = _free_port()
    server = tmp_path / "old_server.py"
    server.write_text(textwrap.dedent(f"""
        from http.server import BaseHTTPRequestHandler, HTTPServer
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b'{{"status": "ok"}}')
            def log_message(self, *a): pass
        HTTPServer(("127.0.0.1", {port}), H).serve_forever()
    """))
    proc = subprocess.Popen([sys.executable, str(server)])
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import run

        for _ in range(40):
            info = run._health("127.0.0.1", port)
            if info:
                break
            time.sleep(0.1)
        assert info == {"status": "ok"}
        assert run._stop_old_server("127.0.0.1", port, info) is True
        proc.wait(timeout=10)
        assert run._health("127.0.0.1", port) is None
    finally:
        if proc.poll() is None:
            proc.kill()
