"""
ffprobe-based media metadata extraction. Pure subprocess + JSON parsing --
no heavy video library dependency needed for this.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, asdict
from fractions import Fraction
from pathlib import Path

from app.errors import UnsupportedMediaError, ExternalToolMissingError
from app.logging_config import get_logger

logger = get_logger("media")

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


@dataclass
class MediaMetadata:
    duration_seconds: float
    width: int
    height: int
    fps: float
    video_codec: str | None
    audio_codec: str | None
    audio_channels: int | None
    has_audio: bool
    file_size_bytes: int
    aspect_ratio: str

    def to_dict(self) -> dict:
        return asdict(self)


def _aspect_ratio_str(width: int, height: int) -> str:
    if not width or not height:
        return "unknown"
    frac = Fraction(width, height).limit_denominator(20)
    return f"{frac.numerator}:{frac.denominator}"


def _parse_fps(rate_str: str | None) -> float:
    if not rate_str or rate_str == "0/0":
        return 0.0
    try:
        if "/" in rate_str:
            num, den = rate_str.split("/")
            den = float(den)
            return round(float(num) / den, 3) if den else 0.0
        return round(float(rate_str), 3)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: Path) -> MediaMetadata:
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedMediaError(
            f"'{path.suffix}' isn't a supported video format.",
            suggestion=f"Use one of: {', '.join(sorted(SUPPORTED_EXTENSIONS))}.",
        )

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ExternalToolMissingError(
            "ffprobe (part of FFmpeg) isn't installed or isn't on PATH.",
            suggestion="Install FFmpeg and make sure it's on your system PATH, then try again.",
        )

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise UnsupportedMediaError(
            "That video took too long to inspect and may be corrupted.",
            suggestion="Try a different file, or re-export it and try again.",
        ) from exc

    if result.returncode != 0 or not result.stdout.strip():
        logger.warning("ffprobe failed for %s: %s", path, result.stderr[:500])
        raise UnsupportedMediaError(
            "ClipForge couldn't read that video file.",
            suggestion="It may be corrupted or use an unsupported codec. Try re-exporting it as MP4 (H.264).",
        )

    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video_stream is None:
        raise UnsupportedMediaError(
            "That file doesn't contain a video track.",
            suggestion="Make sure you're uploading a video file, not an audio-only file.",
        )

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    duration = float(fmt.get("duration") or video_stream.get("duration") or 0.0)

    return MediaMetadata(
        duration_seconds=round(duration, 3),
        width=width,
        height=height,
        fps=_parse_fps(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")),
        video_codec=video_stream.get("codec_name"),
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
        audio_channels=int(audio_stream["channels"]) if audio_stream and audio_stream.get("channels") else None,
        has_audio=audio_stream is not None,
        file_size_bytes=int(fmt.get("size") or path.stat().st_size),
        aspect_ratio=_aspect_ratio_str(width, height),
    )


def extract_audio(video_path: Path, out_wav_path: Path, sample_rate: int = 16000) -> Path:
    """Extract mono PCM audio at `sample_rate` Hz to a WAV file for
    transcription / audio analysis. Raises ExternalToolMissingError /
    UnsupportedMediaError on failure, never a raw ffmpeg stderr dump."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ExternalToolMissingError(
            "FFmpeg isn't installed or isn't on PATH.",
            suggestion="Install FFmpeg and make sure it's on your system PATH, then try again.",
        )

    out_wav_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            ffmpeg, "-y", "-i", str(video_path),
            "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "wav",
            str(out_wav_path),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0 or not out_wav_path.exists():
        logger.warning("ffmpeg audio extraction failed for %s: %s", video_path, result.stderr[:800])
        raise UnsupportedMediaError(
            "Couldn't extract audio from that video.",
            suggestion="The file may have no audio track or use an unsupported codec.",
        )
    return out_wav_path
