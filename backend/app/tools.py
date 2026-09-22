"""
Locating external media tools in a way that works on a fresh Windows machine.

Resolution order for ffmpeg:
  1. CLIPFORGE_FFMPEG_PATH setting (explicit override)
  2. `ffmpeg` on PATH (a system install -- usually the most capable build)
  3. the static build bundled with the `imageio-ffmpeg` pip package, so a user
     who never installed FFmpeg still gets a working pipeline.

ffprobe is optional: imageio-ffmpeg doesn't ship it, so media.probe() falls
back to PyAV (already a faster-whisper dependency) when it's missing.

Every result is cached for the life of the process -- these lookups are hit
on every render and shouldn't re-spawn subprocesses each time.
"""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.config import settings
from app.errors import ExternalToolMissingError
from app.logging_config import get_logger

logger = get_logger("tools")

# On Windows, stop every ffmpeg/ffprobe child from flashing a console window.
SUBPROCESS_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _supports_subtitles(path: str) -> bool:
    try:
        out = subprocess.run(
            [path, "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=15, creationflags=SUBPROCESS_FLAGS,
        )
        return " subtitles " in out.stdout
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def _resolve_ffmpeg() -> str | None:
    override = (settings.ffmpeg_path or "").strip()
    if override and Path(override).is_file():
        return override
    candidates: list[str] = []
    on_path = shutil.which("ffmpeg")
    if on_path:
        candidates.append(on_path)
    try:
        import imageio_ffmpeg  # type: ignore

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).is_file():
            candidates.append(bundled)
    except Exception as exc:  # pragma: no cover - depends on install
        logger.warning("imageio-ffmpeg not usable: %s", exc)
    # Captions need libass: prefer a build that has it (some minimal system
    # FFmpeg builds don't), otherwise take whatever exists.
    for c in candidates:
        if _supports_subtitles(c):
            if c != on_path:
                logger.info("Using bundled FFmpeg (supports captions): %s", c)
            return c
    return candidates[0] if candidates else None


def ffmpeg_path() -> str:
    path = _resolve_ffmpeg()
    if not path:
        raise ExternalToolMissingError(
            "FFmpeg couldn't be found.",
            suggestion=(
                "Re-run the ClipForge setup (it installs a bundled FFmpeg), or install FFmpeg "
                "yourself (e.g. `winget install Gyan.FFmpeg`) and restart ClipForge."
            ),
        )
    return path


def ffmpeg_available() -> bool:
    return _resolve_ffmpeg() is not None


@functools.lru_cache(maxsize=1)
def ffprobe_path() -> str | None:
    override = (settings.ffmpeg_path or "").strip()
    if override:
        candidate = Path(override).with_name("ffprobe" + (".exe" if sys.platform == "win32" else ""))
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ffprobe")


@functools.lru_cache(maxsize=1)
def ffmpeg_version() -> str | None:
    path = _resolve_ffmpeg()
    if not path:
        return None
    try:
        out = subprocess.run(
            [path, "-hide_banner", "-version"],
            capture_output=True, text=True, timeout=10, creationflags=SUBPROCESS_FLAGS,
        )
        return out.stdout.splitlines()[0] if out.stdout else None
    except Exception:  # pragma: no cover
        return None


@functools.lru_cache(maxsize=1)
def _encoders() -> str:
    path = _resolve_ffmpeg()
    if not path:
        return ""
    try:
        out = subprocess.run(
            [path, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=15, creationflags=SUBPROCESS_FLAGS,
        )
        return out.stdout
    except Exception:  # pragma: no cover
        return ""


@functools.lru_cache(maxsize=1)
def _filters() -> str:
    path = _resolve_ffmpeg()
    if not path:
        return ""
    try:
        out = subprocess.run(
            [path, "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=15, creationflags=SUBPROCESS_FLAGS,
        )
        return out.stdout
    except Exception:  # pragma: no cover
        return ""


def has_encoder(name: str) -> bool:
    return f" {name} " in _encoders()


def has_filter(name: str) -> bool:
    return f" {name} " in _filters()


def run_ffmpeg(args: list[str], *, timeout: float | None = None, cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    """Run ffmpeg with `args` (without the binary). Captures output as bytes so
    non-UTF-8 stderr on Windows can never raise a decode error."""
    return subprocess.run(
        [ffmpeg_path(), "-hide_banner", *args],
        capture_output=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        creationflags=SUBPROCESS_FLAGS,
    )


class StderrDrain:
    """Continuously read a subprocess's stderr on a background thread.

    If nobody reads stderr, a chatty ffmpeg (e.g. decoding a damaged file)
    fills the OS pipe buffer -- only 4 KB on Windows -- and blocks forever.
    Keeps the last ~64 KB for error messages."""

    def __init__(self, stream):
        import threading

        self._chunks: list[bytes] = []
        self._stream = stream
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            for chunk in iter(lambda: self._stream.read(4096), b""):
                self._chunks.append(chunk)
                if len(self._chunks) > 32:
                    del self._chunks[:16]
        except Exception:  # pragma: no cover - stream closed
            pass

    def text(self, timeout: float = 2.0) -> str:
        self._thread.join(timeout=timeout)
        return decode(b"".join(self._chunks))


def decode(b: bytes | None) -> str:
    return (b or b"").decode("utf-8", errors="replace")


def escape_filter_path(path: str | Path) -> str:
    """Escape a filesystem path for use inside an ffmpeg filter argument
    (subtitles=..., sendcmd=...). Windows drive letters contain ':' which is
    the filter option separator, and backslashes are escape characters, so
    `C:\\x\\y.ass` must become `C\\:/x/y.ass` wrapped in single quotes."""
    s = str(path).replace("\\", "/")
    s = s.replace(":", "\\:").replace("'", "\\'")
    return f"'{s}'"


def register_gpu_dlls() -> None:
    """On Windows, CTranslate2 (faster-whisper) needs cuBLAS + cuDNN DLLs to use
    an NVIDIA GPU. If the user installed them via pip (scripts/enable-gpu.bat
    installs nvidia-cublas-cu12 / nvidia-cudnn-cu12), their DLL folders aren't
    on the search path by default -- add them here, before ctranslate2 loads.
    Harmless no-op everywhere else."""
    if sys.platform != "win32":
        return
    try:
        import site

        roots = list(site.getsitepackages()) + [site.getusersitepackages()]
    except Exception:  # pragma: no cover
        roots = []
    added = []
    for root in roots:
        nvidia = Path(root) / "nvidia"
        if not nvidia.is_dir():
            continue
        for bin_dir in nvidia.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))  # type: ignore[attr-defined]
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
                added.append(str(bin_dir))
            except Exception as exc:  # pragma: no cover
                logger.warning("Couldn't register GPU DLL dir %s: %s", bin_dir, exc)
    if added:
        logger.info("Registered NVIDIA runtime DLL folders: %s", ", ".join(added))
