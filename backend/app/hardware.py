"""
Hardware detection: CPU, RAM, GPU/VRAM/CUDA, and presence of required local
tools (ffmpeg, ollama). Used to (a) show the user what ClipForge can do on
their machine and (b) let quality-mode selection degrade gracefully instead
of crashing when a resource isn't there.

Never raise from here -- a detection failure means "unknown / unavailable",
not a crash.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field

import psutil
import requests

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("hardware")


@dataclass
class GpuInfo:
    available: bool = False
    name: str | None = None
    vram_total_mb: int | None = None
    vram_free_mb: int | None = None
    cuda_available: bool = False
    detection_method: str | None = None


@dataclass
class HardwareReport:
    cpu_cores_logical: int
    cpu_cores_physical: int | None
    ram_total_mb: int
    ram_available_mb: int
    gpu: GpuInfo
    ffmpeg_available: bool
    ffmpeg_version: str | None
    ollama_reachable: bool
    ollama_models: list[str] = field(default_factory=list)
    recommended_quality_mode: str = "balanced"


def _detect_gpu() -> GpuInfo:
    # Try nvidia-smi first -- works regardless of whether torch is installed.
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            out = subprocess.run(
                [
                    nvidia_smi,
                    "--query-gpu=name,memory.total,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if out.returncode == 0 and out.stdout.strip():
                first_line = out.stdout.strip().splitlines()[0]
                name, total, free = [p.strip() for p in first_line.split(",")]
                return GpuInfo(
                    available=True,
                    name=name,
                    vram_total_mb=int(float(total)),
                    vram_free_mb=int(float(free)),
                    cuda_available=True,
                    detection_method="nvidia-smi",
                )
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("nvidia-smi detection failed: %s", exc)

    # Fall back to torch.cuda if torch happens to be installed.
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            idx = 0
            props = torch.cuda.get_device_properties(idx)
            free, total = torch.cuda.mem_get_info(idx)
            return GpuInfo(
                available=True,
                name=props.name,
                vram_total_mb=int(total / (1024 * 1024)),
                vram_free_mb=int(free / (1024 * 1024)),
                cuda_available=True,
                detection_method="torch",
            )
    except Exception:
        pass

    return GpuInfo(available=False, detection_method="none")


def _detect_ffmpeg() -> tuple[bool, str | None]:
    from app import tools

    if not tools.ffmpeg_available():
        return False, None
    return True, tools.ffmpeg_version()


def _detect_ollama() -> tuple[bool, list[str]]:
    try:
        resp = requests.get(f"{settings.ollama_host}/api/tags", timeout=2)
        if resp.status_code == 200:
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            return True, models
    except Exception:
        pass
    return False, []


def _recommend_quality_mode(ram_total_mb: int, gpu: GpuInfo) -> str:
    if gpu.available and (gpu.vram_total_mb or 0) >= 10000:
        return "maximum_quality"
    if gpu.available and (gpu.vram_total_mb or 0) >= 6000:
        return "high_quality"
    if ram_total_mb >= 8000:
        return "balanced"
    return "fast"


def get_hardware_report() -> HardwareReport:
    vm = psutil.virtual_memory()
    gpu = _detect_gpu()
    ffmpeg_available, ffmpeg_version = _detect_ffmpeg()
    ollama_reachable, ollama_models = _detect_ollama()

    ram_total_mb = int(vm.total / (1024 * 1024))

    report = HardwareReport(
        cpu_cores_logical=psutil.cpu_count(logical=True) or 1,
        cpu_cores_physical=psutil.cpu_count(logical=False),
        ram_total_mb=ram_total_mb,
        ram_available_mb=int(vm.available / (1024 * 1024)),
        gpu=gpu,
        ffmpeg_available=ffmpeg_available,
        ffmpeg_version=ffmpeg_version,
        ollama_reachable=ollama_reachable,
        ollama_models=ollama_models,
        recommended_quality_mode=_recommend_quality_mode(ram_total_mb, gpu),
    )
    return report
