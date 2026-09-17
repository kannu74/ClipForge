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

from app.errors import ExternalToolMissingError, ValidationFailedError
from app.logging_config import get_logger

logger = get_logger("youtube")

_YOUTUBE_PATTERNS = [
    re.compile(r"^https?://(www\.)?youtube\.com/watch\?v=(?P<id>[\w-]{11})"),
    re.compile(r"^https?://(www\.)?youtube\.com/shorts/(?P<id>[\w-]{11})"),
    re.compile(r"^https?://youtu\.be/(?P<id>[\w-]{11})"),
    re.compile(r"^https?://(www\.)?youtube\.com/embed/(?P<id>[\w-]{11})"),
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


def download(url: str, out_dir: Path) -> tuple[Path, dict]:
    """Download the video locally with yt-dlp. Returns (file_path, info_dict).
    Raises ExternalToolMissingError / ValidationFailedError with plain-language
    messages -- never a raw yt-dlp traceback."""
    video_id = extract_video_id(url)

    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - dependency always installed via requirements.txt
        raise ExternalToolMissingError(
            "The YouTube downloader (yt-dlp) isn't installed.",
            suggestion="Run `pip install -r requirements.txt` in the backend and try again.",
        ) from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(out_dir / f"{video_id}.%(ext)s")

    ydl_opts = {
        "outtmpl": out_template,
        "format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        logger.warning("yt-dlp failed for %s: %s", url, exc)
        raise ValidationFailedError(
            "Couldn't download that YouTube video.",
            suggestion=(
                "It may be private, age-restricted, region-locked, or removed. "
                "ClipForge only works with videos you're allowed to access."
            ),
            detail=str(exc),
        ) from exc

    downloaded_path = out_dir / f"{video_id}.mp4"
    if not downloaded_path.exists():
        # yt-dlp may have picked a different final extension; find whatever landed.
        matches = list(out_dir.glob(f"{video_id}.*"))
        if not matches:
            raise ValidationFailedError(
                "The video downloaded but ClipForge couldn't find the resulting file.",
                suggestion="Try again, or report this as a bug.",
            )
        downloaded_path = matches[0]

    return downloaded_path, info or {}
