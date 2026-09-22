"""
Which version of the code is running?

On Windows ClipForge stays open in a console window. When the code is updated
while that window is still open, starting ClipForge.bat again used to just
re-open the browser on the *old* server -- so fixes silently didn't apply
(this happened on the first real run: renders kept failing with a bug that
was already fixed on disk). A content fingerprint of the backend code and
the built UI lets the launcher and the UI notice a stale server.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
_PATTERNS = ("app/**/*.py", "app/static/index.html", "requirements.txt")


def code_fingerprint(root: Path = BACKEND_DIR) -> str:
    h = hashlib.sha1()
    files: set[Path] = set()
    for pat in _PATTERNS:
        files.update(p for p in root.glob(pat) if p.is_file() and "__pycache__" not in p.parts)
    for p in sorted(files):
        h.update(p.relative_to(root).as_posix().encode())
        try:
            # Normalise line endings so a git autocrlf checkout doesn't differ.
            h.update(p.read_bytes().replace(b"\r\n", b"\n"))
        except OSError:
            continue
    return h.hexdigest()[:16]


# Fingerprint of the code this process actually imported.
RUNNING = code_fingerprint()
_disk_cache: tuple[float, str] = (0.0, RUNNING)


def on_disk(max_age: float = 15.0) -> str:
    """Fingerprint of the code currently on disk (cached for a few seconds)."""
    global _disk_cache
    ts, fp = _disk_cache
    if time.time() - ts > max_age:
        fp = code_fingerprint()
        _disk_cache = (time.time(), fp)
    return fp


def update_pending() -> bool:
    return on_disk() != RUNNING
