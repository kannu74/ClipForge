"""
Media metadata extraction (ffprobe, or PyAV when ffprobe isn't installed)
plus audio/frame extraction via ffmpeg (see app/tools.py for how the
binaries are located on a fresh machine).
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict
from fractions import Fraction
from pathlib import Path

from app import tools
from app.errors import UnsupportedMediaError, ExternalToolMissingError
from app.logging_config import get_logger

logger = get_logger("media")

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".ts", ".mts", ".3gp"}


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

    ffprobe = tools.ffprobe_path()
    if ffprobe:
        return _probe_ffprobe(ffprobe, path)
    # No ffprobe (e.g. only the bundled imageio-ffmpeg is available): PyAV
    # reads the same container metadata without a separate binary.
    return _probe_pyav(path)


def _probe_ffprobe(ffprobe: str, path: Path) -> MediaMetadata:
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
            timeout=60,
            creationflags=tools.SUBPROCESS_FLAGS,
        )
    except subprocess.TimeoutExpired as exc:
        raise UnsupportedMediaError(
            "That video took too long to inspect and may be corrupted.",
            suggestion="Try a different file, or re-export it and try again.",
        ) from exc

    stdout = tools.decode(result.stdout)
    if result.returncode != 0 or not stdout.strip():
        logger.warning("ffprobe failed for %s: %s", path, tools.decode(result.stderr)[:500])
        raise UnsupportedMediaError(
            "ClipForge couldn't read that video file.",
            suggestion="It may be corrupted or use an unsupported codec. Try re-exporting it as MP4 (H.264).",
        )

    data = json.loads(stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video_stream = next(
        (s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")),
        None,
    )
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video_stream is None:
        raise UnsupportedMediaError(
            "That file doesn't contain a video track.",
            suggestion="Make sure you're uploading a video file, not an audio-only file.",
        )

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    rotation = _rotation_from_stream(video_stream)
    if rotation in (90, 270):
        width, height = height, width
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


def _rotation_from_stream(stream: dict) -> int:
    try:
        tag = (stream.get("tags") or {}).get("rotate")
        if tag is not None:
            return int(tag) % 360
        for side in stream.get("side_data_list") or []:
            if "rotation" in side:
                return int(side["rotation"]) % 360
    except (TypeError, ValueError):
        pass
    return 0


def _probe_pyav(path: Path) -> MediaMetadata:
    try:
        import av  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ExternalToolMissingError(
            "ClipForge can't inspect videos: neither ffprobe nor PyAV is available.",
            suggestion="Re-run the ClipForge setup, or install FFmpeg and restart.",
        ) from exc
    try:
        with av.open(str(path)) as container:
            vstreams = [s for s in container.streams.video]
            if not vstreams:
                raise UnsupportedMediaError(
                    "That file doesn't contain a video track.",
                    suggestion="Make sure you're uploading a video file, not an audio-only file.",
                )
            v = vstreams[0]
            a = container.streams.audio[0] if container.streams.audio else None
            width = int(v.codec_context.width or 0)
            height = int(v.codec_context.height or 0)
            if container.duration:
                duration = float(container.duration) / 1_000_000
            elif v.duration and v.time_base:
                duration = float(v.duration * v.time_base)
            else:
                duration = 0.0
            rate = v.average_rate or v.guessed_rate
            fps = round(float(rate), 3) if rate else 0.0
            return MediaMetadata(
                duration_seconds=round(duration, 3),
                width=width,
                height=height,
                fps=fps,
                video_codec=v.codec_context.name,
                audio_codec=a.codec_context.name if a else None,
                audio_channels=int(a.codec_context.channels) if a and a.codec_context.channels else None,
                has_audio=a is not None,
                file_size_bytes=path.stat().st_size,
                aspect_ratio=_aspect_ratio_str(width, height),
            )
    except UnsupportedMediaError:
        raise
    except Exception as exc:
        logger.warning("PyAV probe failed for %s: %s", path, exc)
        raise UnsupportedMediaError(
            "ClipForge couldn't read that video file.",
            suggestion="It may be corrupted or use an unsupported codec. Try re-exporting it as MP4 (H.264).",
        ) from exc


def extract_audio(
    video_path: Path,
    out_wav_path: Path,
    sample_rate: int = 16000,
    start: float | None = None,
    end: float | None = None,
) -> Path:
    """Extract mono PCM audio at `sample_rate` Hz to a WAV file for
    transcription / audio analysis, optionally only [start, end) seconds.
    Raises ExternalToolMissingError / UnsupportedMediaError on failure, never
    a raw ffmpeg stderr dump."""
    out_wav_path.parent.mkdir(parents=True, exist_ok=True)
    args = ["-y"]
    if start is not None and start > 0:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(video_path)]
    if end is not None and end > 0:
        dur = end - (start or 0.0)
        if dur > 0:
            args += ["-t", f"{dur:.3f}"]
    args += ["-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "wav", str(out_wav_path)]
    try:
        result = tools.run_ffmpeg(args, timeout=3600)
    except subprocess.TimeoutExpired as exc:
        raise UnsupportedMediaError("Extracting audio took too long.") from exc
    if result.returncode != 0 or not out_wav_path.exists():
        logger.warning("ffmpeg audio extraction failed for %s: %s", video_path, tools.decode(result.stderr)[-800:])
        raise UnsupportedMediaError(
            "Couldn't extract audio from that video.",
            suggestion="The file may have no audio track or use an unsupported codec.",
        )
    return out_wav_path


def extract_frame(video_path: Path, t: float, out_path: Path, width: int = 640) -> Path:
    """Grab a single frame at time `t` as a JPEG (used for thumbnails and the
    editor's facecam picker)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = tools.run_ffmpeg(
        [
            "-y", "-ss", f"{max(t, 0):.3f}", "-i", str(video_path),
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(out_path),
        ],
        timeout=60,
    )
    if result.returncode != 0 or not out_path.exists():
        logger.warning("Frame extraction failed at %.2fs: %s", t, tools.decode(result.stderr)[-400:])
        raise UnsupportedMediaError("Couldn't grab a preview frame from that video.")
    return out_path
