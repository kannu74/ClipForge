"""
Start ClipForge: the API and the built web UI in one process, then open the
browser. Used by ClipForge.bat (Windows) and `python run.py` anywhere.

  - If the same version of ClipForge is already running, just opens the
    browser again. If an OLDER version is still running (ClipForge was
    updated while its window stayed open), that server is stopped and the
    new one started -- otherwise updates silently wouldn't apply.
  - If the configured port is taken by something else, picks the next free one.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)  # .env and ./data are relative to backend/
sys.path.insert(0, str(HERE))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
# The Xet transfer backend failed mid-download on a real Windows first run
# ("CAS Client Error"); plain HTTPS downloads are slower to start but reliable.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def _health(host: str, port: int) -> dict | None:
    """The running ClipForge's health payload, or None if it isn't ClipForge."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/system/health", timeout=1.5) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
            return data if isinstance(data, dict) and data.get("status") == "ok" else None
    except Exception:
        return None


def _is_clipforge(host: str, port: int) -> bool:
    return _health(host, port) is not None


def _pid_listening_on(port: int) -> int | None:
    try:
        import psutil

        for c in psutil.net_connections(kind="tcp"):
            if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN and c.pid:
                return c.pid
    except Exception:
        pass
    return None


def _stop_old_server(host: str, port: int, info: dict) -> bool:
    """Stop an outdated ClipForge that is still serving on `port`."""
    try:
        import psutil
    except Exception:
        return False
    pid = info.get("pid") or _pid_listening_on(port)
    if not pid or pid == os.getpid():
        return False
    try:
        proc = psutil.Process(int(pid))
        name = (proc.name() or "").lower()
        if "python" not in name:  # never kill something that isn't ours
            return False
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except psutil.NoSuchProcess:
        pass
    except Exception as exc:
        print(f"  Couldn't stop the old ClipForge ({exc}).")
        return False
    for _ in range(40):  # wait for the port to be released
        if not _is_clipforge(host, port):
            return True
        time.sleep(0.25)
    return not _is_clipforge(host, port)


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def main() -> None:
    from app.config import settings

    host = settings.host
    port = settings.port
    url_host = "127.0.0.1" if host in ("0.0.0.0", "") else host

    running = _health(url_host, port)
    if running is not None:
        from app.buildinfo import code_fingerprint

        if running.get("build") == code_fingerprint():
            print(f"ClipForge is already running -- opening http://{url_host}:{port}")
            webbrowser.open(f"http://{url_host}:{port}")
            return
        print("")
        print("  An older version of ClipForge is still running. Restarting it with the update...")
        if not _stop_old_server(url_host, port, running):
            print("  Please close the other ClipForge window, then start ClipForge.bat again.")
            print("  (Until then the old version keeps running and the update isn't used.)")
            webbrowser.open(f"http://{url_host}:{port}")
            return
        print("  Old version stopped. Anything it was rendering will resume automatically.")
    while not _port_free(host, port) and port < settings.port + 20:
        port += 1
    url = f"http://{url_host}:{port}"

    def _open_when_ready() -> None:
        for _ in range(120):
            if _is_clipforge(url_host, port):
                webbrowser.open(url)
                return
            time.sleep(0.5)

    if "--no-browser" not in sys.argv:
        threading.Thread(target=_open_when_ready, daemon=True).start()

    print("")
    print("  ClipForge is starting at " + url)
    print("  Keep this window open while you use ClipForge. Close it to stop.")
    print("")
    import uvicorn

    uvicorn.run("app.main:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
