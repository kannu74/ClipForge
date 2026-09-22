"""System/health endpoints: liveness + hardware report for the UI's
hardware-awareness display and quality-mode recommendation."""
from __future__ import annotations

from fastapi import APIRouter

from app.hardware import get_hardware_report
from app.models import GpuInfoOut, HardwareReportOut

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/hardware", response_model=HardwareReportOut)
def hardware() -> HardwareReportOut:
    report = get_hardware_report()
    return HardwareReportOut(
        cpu_cores_logical=report.cpu_cores_logical,
        cpu_cores_physical=report.cpu_cores_physical,
        ram_total_mb=report.ram_total_mb,
        ram_available_mb=report.ram_available_mb,
        gpu=GpuInfoOut(
            available=report.gpu.available,
            name=report.gpu.name,
            vram_total_mb=report.gpu.vram_total_mb,
            vram_free_mb=report.gpu.vram_free_mb,
            cuda_available=report.gpu.cuda_available,
        ),
        ffmpeg_available=report.ffmpeg_available,
        ffmpeg_version=report.ffmpeg_version,
        ollama_reachable=report.ollama_reachable,
        ollama_models=report.ollama_models,
        recommended_quality_mode=report.recommended_quality_mode,
    )


@router.get("/capabilities")
def capabilities() -> dict:
    """What this install can actually do -- the UI uses it to explain any
    missing piece in plain language instead of failing later."""
    from app import tools
    from app.captions import STYLES
    from app.config import settings
    from app.reframe import MODEL_PATH, describe_modes

    def _ver(mod: str) -> str | None:
        try:
            from importlib.metadata import version

            return version(mod)
        except Exception:
            return None

    try:
        import cv2  # type: ignore  # noqa: F401

        opencv = True
    except Exception:
        opencv = False
    try:
        from deno import find_deno_bin  # type: ignore

        find_deno_bin()
        deno = True
    except Exception:
        deno = False
    return {
        "ffmpeg": {
            "available": tools.ffmpeg_available(),
            "version": tools.ffmpeg_version(),
            "captions_supported": tools.has_filter("subtitles"),
            "nvenc": tools.has_encoder("h264_nvenc"),
        },
        "face_detection": opencv and MODEL_PATH.exists(),
        "youtube": {"yt_dlp": _ver("yt-dlp"), "js_runtime": deno},
        "whisper": {
            "default_model": settings.whisper_model_size,
            "models": ["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"],
            "device": settings.whisper_device,
            "faster_whisper": _ver("faster-whisper"),
        },
        "caption_styles": list(STYLES.keys()),
        "reframe_modes": describe_modes(),
        "version": "1.0.0",
    }


@router.get("/fonts/{name}")
def font_file(name: str):
    """Caption fonts, so the editor's live preview uses the exact typefaces
    the renderer burns in."""
    from fastapi.responses import FileResponse

    from app.captions import FONTS_DIR
    from app.errors import NotFoundError

    path = (FONTS_DIR / name).resolve()
    if path.suffix.lower() != ".ttf" or FONTS_DIR.resolve() not in path.parents or not path.exists():
        raise NotFoundError("Font not found.")
    return FileResponse(path, media_type="font/ttf", headers={"Cache-Control": "max-age=86400"})
