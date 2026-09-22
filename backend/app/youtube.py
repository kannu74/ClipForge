"""
YouTube URL validation + local download via yt-dlp.

Validation is pure/offline (regex) so it's fully unit-testable without
network. The actual download requires internet access to youtube.com and
is the one piece of the pipeline that's allowed to touch the network by
design (see CLAUDE.md: local-first except for the explicit YouTube fetch).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from app.config import settings
from app.errors import ExternalToolMissingError, ValidationFailedError
from app.logging_config import get_logger

logger = get_logger("youtube")

_YOUTUBE_PATTERNS = [
    re.compile(r"^https?://(www\.)?youtube\.com/watch\?v=(?P<id>[\w-]{11})"),
    re.compile(r"^https?://(www\.)?youtube\.com/shorts/(?P<id>[\w-]{11})"),
    re.compile(r"^https?://youtu\.be/(?P<id>[\w-]{11})"),
    re.compile(r"^https?://(www\.)?youtube\.com/embed/(?P<id>[\w-]{11})"),
    re.compile(r"^https?://(www\.|m\.)?youtube\.com/live/(?P<id>[\w-]{11})"),
    re.compile(r"^https?://m\.youtube\.com/watch\?(.*&)?v=(?P<id>[\w-]{11})"),
    re.compile(r"^https?://(www\.)?youtube\.com/watch\?(.*&)?v=(?P<id>[\w-]{11})"),
    re.compile(r"^https?://music\.youtube\.com/watch\?(.*&)?v=(?P<id>[\w-]{11})"),
]


def extract_video_id(url: str) -> str:
    """Validate a YouTube URL and return its 11-char video id.
    Raises ValidationFailedError with a plain-language message if the URL
    isn't a recognizable YouTube video/shorts link."""
    url = url.strip()
    for pattern in _YOUTUBE_PATTERNS:
        match = pattern.match(url)
        if match:
            return match.group("id")
    raise ValidationFailedError(
        "That doesn't look like a YouTube video URL.",
        suggestion="Paste a link like https://www.youtube.com/watch?v=... or https://youtu.be/...",
    )


def _js_runtimes() -> dict:
    """yt-dlp now needs a JavaScript runtime to solve YouTube's player
    challenges. The `deno` pip package (installed with requirements.txt)
    ships one; Node.js is used as a fallback if the user has it."""
    runtimes: dict = {}
    try:
        from deno import find_deno_bin  # type: ignore

        runtimes["deno"] = {"path": find_deno_bin()}
    except Exception:
        runtimes["deno"] = {}
    runtimes["node"] = {}
    return runtimes


def download(
    url: str,
    out_dir: Path,
    on_progress: Callable[[float, str], None] | None = None,
    section: tuple[float, float | None] | None = None,
) -> tuple[Path, dict]:
    """Download the video locally with yt-dlp. Returns (file_path, info_dict).
    Raises ExternalToolMissingError / ValidationFailedError with plain-language
    messages -- never a raw yt-dlp traceback."""
    video_id = extract_video_id(url)

    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - dependency always installed via requirements.txt
        raise ExternalToolMissingError(
            "The YouTube downloader (yt-dlp) isn't installed.",
            suggestion="Re-run the ClipForge setup and try again.",
        ) from exc

    from app import tools

    out_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(out_dir / f"{video_id}.%(ext)s")

    def _hook(d: dict) -> None:
        if on_progress is None:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            frac = (done / total) if total else 0.0
            speed = d.get("speed") or 0
            msg = f"Downloading from YouTube ({done / 1e6:.0f} MB"
            msg += f" of {total / 1e6:.0f} MB" if total else ""
            msg += f", {speed / 1e6:.1f} MB/s)" if speed else ")"
            on_progress(min(frac, 1.0), msg)
        elif d.get("status") == "finished":
            on_progress(1.0, "Download finished, merging audio and video...")

    ydl_opts: dict = {
        "outtmpl": out_template,
        # Prefer H.264 + AAC (plays in every browser and decodes fastest);
        # fall back to whatever YouTube offers up to 1080p.
        "format": (
            "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/"
            "bv*[height<=1080]+ba/"
            "b[height<=1080]/b"
        ),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [_hook],
        "js_runtimes": _js_runtimes(),
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
    }
    try:
        ydl_opts["ffmpeg_location"] = tools.ffmpeg_path()
    except Exception:
        pass
    browser = (settings.youtube_cookies_browser or "").strip().lower()
    if browser:
        ydl_opts["cookiesfrombrowser"] = (browser,)
    if section is not None:
        # Only fetch the part the creator asked for -- a 20-minute slice of a
        # 4-hour stream downloads in a fraction of the time.
        from yt_dlp.utils import download_range_func

        s_start, s_end = section
        ydl_opts["download_ranges"] = download_range_func(None, [(float(s_start or 0), float(s_end) if s_end else float("inf"))])
        ydl_opts["force_keyframes_at_cuts"] = True

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        logger.warning("yt-dlp failed for %s: %s", url, exc)
        text = str(exc).lower()
        if "sign in" in text or "not a bot" in text or "cookies" in text:
            suggestion = (
                "YouTube is asking for a sign-in check. Set CLIPFORGE_YOUTUBE_COOKIES_BROWSER=firefox "
                "(or edge/chrome) in backend/.env so ClipForge can use your browser's YouTube login, "
                "or download the video yourself and upload the file instead."
            )
        elif "private" in text or "unavailable" in text or "removed" in text:
            suggestion = "The video may be private, removed, or region-locked. Try another link or upload the file."
        elif "ffmpeg" in text:
            suggestion = "FFmpeg is needed to merge YouTube's audio and video. Re-run ClipForge setup."
        else:
            suggestion = (
                "Check your internet connection. If it keeps failing, YouTube may have changed something -- "
                "re-running the ClipForge setup updates the downloader. You can always upload the file instead."
            )
        raise ValidationFailedError(
            "Couldn't download that YouTube video.",
            suggestion=suggestion,
            detail=str(exc),
        ) from exc

    downloaded_path = out_dir / f"{video_id}.mp4"
    if not downloaded_path.exists():
        # yt-dlp may have picked a different final extension; find whatever landed.
        matches = [p for p in out_dir.glob(f"{video_id}.*") if not p.name.endswith((".part", ".ytdl"))]
        if not matches:
            raise ValidationFailedError(
                "The video downloaded but ClipForge couldn't find the resulting file.",
                suggestion="Try again, or upload the video file directly.",
            )
        downloaded_path = matches[0]

    return downloaded_path, info or {}
