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
