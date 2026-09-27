"""
Phase 9/10 -- rendering and automated QC.

One ffmpeg pass per clip: seek -> reframe filtergraph -> burned-in captions
-> H.264/AAC MP4 with loudness normalised for social platforms (-14 LUFS)
and tiny audio fades so cuts never click. NVIDIA hardware encoding is used
when available and silently falls back to x264 if it fails.

After encoding, an automated QC pass checks the output a creator would
otherwise have to check by eye: right duration and resolution, audio
present and not silent, not mostly black frames. Problems are attached to
the clip as plain-language warnings (the file is still delivered -- the
creator decides).
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app import captions, media, reframe, storage, tools
from app.config import settings
from app.errors import ClipForgeError, ExternalToolMissingError
from app.logging_config import get_logger
from app.project_settings import CaptionSettings, ReframeSettings, RenderSettings
from app.units import Unit, words_in_range

logger = get_logger("render")

ProgressFn = Callable[[float, str], None]

X264_PRESET = {"fast": "veryfast", "balanced": "faster", "high": "medium"}
X264_CRF = {"fast": 23, "balanced": 20, "high": 18}
NVENC_PRESET = {"fast": "p3", "balanced": "p5", "high": "p6"}
NVENC_CQ = {"fast": 25, "balanced": 21, "high": 19}


class RenderFailedError(ClipForgeError):
    status_code = 500


def _encoder_args(kind: str, quality: str) -> list[str]:
    if kind == "nvenc":
        return [
            "-c:v", "h264_nvenc", "-preset", NVENC_PRESET[quality], "-rc", "vbr",
            "-cq", str(NVENC_CQ[quality]), "-b:v", "0", "-profile:v", "high", "-pix_fmt", "yuv420p",
        ]
    return [
        "-c:v", "libx264", "-preset", X264_PRESET[quality], "-crf", str(X264_CRF[quality]),
        "-profile:v", "high", "-pix_fmt", "yuv420p",
    ]


def _encoders_to_try() -> list[str]:
    pref = (settings.video_encoder or "auto").lower()
    if pref == "x264":
        return ["x264"]
    nvenc_ok = tools.has_encoder("h264_nvenc")
    if pref == "nvenc":
        return ["nvenc", "x264"] if nvenc_ok else ["x264"]
    try:
        from app.hardware import _detect_gpu

        gpu = _detect_gpu().available
    except Exception:  # pragma: no cover
        gpu = False
    return ["nvenc", "x264"] if (nvenc_ok and gpu) else ["x264"]


def _run_with_progress(args: list[str], duration: float, cwd: Path, on_progress: ProgressFn | None, label: str) -> tuple[int, str]:
    cmd = [tools.ffmpeg_path(), "-hide_banner", "-nostats", "-progress", "pipe:1", *args]
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=tools.SUBPROCESS_FLAGS
    )
    stderr_chunks: list[bytes] = []

    import threading

    def _drain() -> None:
        assert proc.stderr is not None
        for chunk in iter(lambda: proc.stderr.read(4096), b""):
            stderr_chunks.append(chunk)
            if len(stderr_chunks) > 400:
                del stderr_chunks[:200]

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    last = 0.0
    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                frac = min(max(us / 1_000_000 / max(duration, 0.01), 0.0), 1.0)
                now = time.time()
                if on_progress and now - last > 0.5:
                    last = now
                    on_progress(frac, f"{label} {int(frac * 100)}%")
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    proc.wait()
    t.join(timeout=2)
    return proc.returncode, tools.decode(b"".join(stderr_chunks))


def caption_words_for_clip(clip: dict, units: list[Unit]) -> list:
    if clip.get("caption_words"):
        return clip["caption_words"]
    return words_in_range(units, clip["start"], clip["end"])


def render_clip(
    project_id: str,
    clip: dict,
    units: list[Unit],
    cap_cfg: CaptionSettings,
    ref_cfg: ReframeSettings,
    render_cfg: RenderSettings,
    source: Path,
    meta: dict,
    on_progress: ProgressFn | None = None,
    workflow_mode: str = "clip_finder",
) -> dict:
    """Render one clip. Returns the render info dict stored on the clip."""
    rdir = storage.renders_dir(project_id)
    clip_id = clip["id"]
    start, end = float(clip["start"]), float(clip["end"])
    duration = end - start
    src_w, src_h = int(meta.get("width") or 0), int(meta.get("height") or 0)
    if not src_w or not src_h:
        m = media.probe(source)
        src_w, src_h = m.width, m.height
    source_preserving = workflow_mode == "captions_only" and render_cfg.output_mode == "source"
    out_w, out_h = (src_w, src_h) if source_preserving else reframe.output_size(ref_cfg.aspect, render_cfg.resolution)
    report = on_progress or (lambda f, m: None)

    # 1. Reframe analysis (cached per clip window).
    analysis = None
    needs_analysis = workflow_mode != "captions_only" and (
        ref_cfg.mode in ("auto", "track") or (ref_cfg.mode == "split" and ref_cfg.facecam is None)
    )
    if needs_analysis:
        report(0.02, "Finding faces for smart framing...")
        try:
            analysis = reframe.analyze(
                source, start, end, src_w, src_h, out_w / out_h, cache=rdir / f"{clip_id}.faces.json"
            )
        except ExternalToolMissingError:
            raise
        except Exception as exc:  # never let analysis kill a render
            logger.warning("Face analysis failed for clip %s: %s", clip_id, exc)
            analysis = None
    if source_preserving:
        rplan = reframe.ReframePlan(
            mode="original",
            filter_complex="[0:v]null[vout]",
            caption_y=None,
            note="Original source format.",
        )
    else:
        rplan = reframe.plan(ref_cfg, src_w, src_h, out_w, out_h, analysis, rdir, clip_id)

    # 2. Captions (.ass burned in, .srt alongside).
    report(0.08, "Building captions...")
    words = caption_words_for_clip(clip, units)
    ass_path, srt_path = captions.write_caption_files(
        words, start, end, cap_cfg, out_w, out_h, rdir / f"{clip_id}.ass", rdir / f"{clip_id}.srt",
        # The default "lower" position adapts to the layout (split seam, or just
        # under the video band in full-frame mode); explicit choices are kept.
        y_override=rplan.caption_y if cap_cfg.position == "lower" else None,
        title=clip.get("title") or "",
        # In the split layout the top is the facecam panel: keep the title
        # small and at the very top so it doesn't cover the face.
        title_top=0.03 if rplan.mode == "split" else 0.07,
    )
    fc = rplan.filter_complex
    if ass_path is not None:
        fontsdir = captions.fonts_dir_for_render(rdir)
        fc = fc.replace("[vout]", "[vpre]") + f";[vpre]subtitles={ass_path.name}:fontsdir={fontsdir}[vout]"

    fps = float(meta.get("fps") or 30.0)
    out_fps = min(fps if fps > 0 else 30.0, 60.0)
    fade_out_at = max(duration - 0.08, 0)
    audio_filter = (
        f"afade=t=in:st=0:d=0.04,afade=t=out:st={fade_out_at:.3f}:d=0.08,"
        "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000"
    )
    has_audio = bool(meta.get("has_audio", True))
    tmp_out = rdir / f"{clip_id}.rendering.mp4"
    final_out = rdir / f"{clip_id}.mp4"

    last_err = ""
    used = None
    for enc in _encoders_to_try():
        args = [
            "-y", "-ss", f"{start:.3f}", "-i", str(Path(source).resolve()), "-t", f"{duration:.3f}",
            "-filter_complex", fc, "-map", "[vout]",
        ]
        if has_audio:
            args += ["-map", "0:a:0?", "-af", audio_filter, "-c:a", "aac", "-b:a", "160k", "-ac", "2"]
        args += ["-r", f"{out_fps:.3f}", *_encoder_args(enc, render_cfg.quality)]
        args += ["-movflags", "+faststart", "-max_muxing_queue_size", "4096", tmp_out.name]
        label = "Rendering (GPU)" if enc == "nvenc" else "Rendering"
        code, err = _run_with_progress(
            args, duration, rdir, (lambda f, m: report(0.1 + 0.8 * f, m)), label
        )
        if code == 0 and tmp_out.exists() and tmp_out.stat().st_size > 1000:
            used = enc
            break
        last_err = err
        logger.warning("Render with %s failed for clip %s: %s", enc, clip_id, err[-1500:])
        tmp_out.unlink(missing_ok=True)
    if used is None:
        hint = "Try a different caption style or framing mode, or re-render."
        if "No such filter" in last_err or "subtitles" in last_err.lower():
            hint = "Your FFmpeg build lacks subtitle support. Re-run ClipForge setup (it installs a compatible FFmpeg)."
        raise RenderFailedError("Couldn't render this clip.", suggestion=hint, detail=last_err[-2000:])

    os.replace(tmp_out, final_out)

    # 3. Thumbnail + QC.
    report(0.92, "Checking the result...")
    thumb = rdir / f"{clip_id}.jpg"
    try:
        media.extract_frame(final_out, min(1.0, duration / 3), thumb, width=360)
    except Exception as exc:
        logger.warning("Thumbnail failed for clip %s: %s", clip_id, exc)
    qc = quality_check(final_out, duration, out_w, out_h, has_audio)

    return {
        "status": "done",
        "file": final_out.name,
        "thumbnail": thumb.name if thumb.exists() else None,
        "srt": srt_path.name,
        "width": out_w,
        "height": out_h,
        "duration": round(duration, 2),
        "size_bytes": final_out.stat().st_size,
        "encoder": used,
        "reframe_mode": rplan.mode,
        "reframe_note": rplan.note,
        "facecam_detected": (analysis.facecam if analysis else None),
        "qc": qc,
        "rendered_at": datetime.now(timezone.utc).isoformat(),
    }


_MEAN_VOL_RE = re.compile(r"mean_volume:\s*(-?[\d.]+) dB")
_BLACK_RE = re.compile(r"black_duration:\s*([\d.]+)")


def quality_check(path: Path, expected_duration: float, out_w: int, out_h: int, expect_audio: bool) -> dict:
    warnings: list[str] = []
    try:
        m = media.probe(path)
        if abs(m.duration_seconds - expected_duration) > max(0.6, expected_duration * 0.03):
            warnings.append(
                f"Length is {m.duration_seconds:.1f}s but {expected_duration:.1f}s was expected."
            )
        if (m.width, m.height) != (out_w, out_h):
            warnings.append(f"Resolution is {m.width}x{m.height}, expected {out_w}x{out_h}.")
        if expect_audio and not m.has_audio:
            warnings.append("The rendered clip has no audio track.")
    except Exception as exc:
        warnings.append("Couldn't read the rendered file back to check it.")
        logger.warning("QC probe failed for %s: %s", path, exc)
        return {"passed": False, "warnings": warnings}

    r = tools.run_ffmpeg(
        [
            "-i", str(path), "-vf", "scale=160:-2,blackdetect=d=0.5:pix_th=0.08",
            "-af", "volumedetect", "-f", "null", "-",
        ],
        timeout=300,
    )
    err = tools.decode(r.stderr)
    black = sum(float(x) for x in _BLACK_RE.findall(err))
    if expected_duration > 0 and black / expected_duration > 0.5:
        warnings.append(f"About {black:.0f}s of the clip is black screen.")
    mv = _MEAN_VOL_RE.search(err)
    mean_volume = float(mv.group(1)) if mv else None
    if expect_audio and mean_volume is not None and mean_volume < -45:
        warnings.append("The audio is almost silent.")
    return {"passed": not warnings, "warnings": warnings, "mean_volume_db": mean_volume, "black_seconds": round(black, 1)}
