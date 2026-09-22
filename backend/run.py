"""
Start ClipForge: the API and the built web UI in one process, then open the
browser. Used by ClipForge.bat (Windows) and `python run.py` anywhere.

  - If ClipForge is already running, just opens the browser again.
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


def _is_clipforge(host: str, port: int) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/system/health", timeout=1.5) as r:
            return b'"ok"' in r.read()
    except Exception:
        return False


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

    if _is_clipforge(url_host, port):
        print(f"ClipForge is already running -- opening http://{url_host}:{port}")
        webbrowser.open(f"http://{url_host}:{port}")
        return
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
