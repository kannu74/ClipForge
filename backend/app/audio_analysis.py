"""
Deterministic audio-energy analysis. No ML model, no network -- just decode
PCM via ffmpeg and compute short-time RMS loudness over time with numpy.
This is the non-LLM signal moment detection leans on (spec: "do not rely
solely on an LLM's subjective score; use deterministic information where
possible"), and it works identically whether or not Ollama is reachable.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app import tools
from app.errors import UnsupportedMediaError
from app.logging_config import get_logger

logger = get_logger("audio_analysis")

SAMPLE_RATE = 8000  # plenty for loudness; halves memory on multi-hour videos
WINDOW_SECONDS = 0.5  # loudness resolution


@dataclass
class EnergyProfile:
    window_seconds: float
    rms: np.ndarray  # loudness per window, linear scale
    rms_db: np.ndarray  # loudness per window, dBFS-ish (relative)
    mean_rms: float
    std_rms: float

    def window_index(self, t: float) -> int:
        idx = int(t / self.window_seconds)
        return max(0, min(idx, len(self.rms) - 1))

    def z_score_at(self, t: float) -> float:
        if self.std_rms <= 1e-9:
            return 0.0
        return (self.rms[self.window_index(t)] - self.mean_rms) / self.std_rms

    def peak_z_in_range(self, start: float, end: float) -> float:
        i0, i1 = self.window_index(start), self.window_index(end)
        if i1 < i0:
            i0, i1 = i1, i0
        window = self.rms[i0 : i1 + 1]
        if len(window) == 0 or self.std_rms <= 1e-9:
            return 0.0
        return float((window.max() - self.mean_rms) / self.std_rms)


def compute_energy_profile(audio_path, window_seconds: float = WINDOW_SECONDS) -> EnergyProfile:
    """Decode audio (any ffmpeg-readable file, including the source video
    itself) and compute windowed RMS loudness. Streams PCM in chunks so a
    multi-hour video never has to fit in memory as raw samples."""
    window_size = max(1, int(SAMPLE_RATE * window_seconds))
    chunk_bytes = window_size * 4 * 2048  # ~17 min of audio per read at 8 kHz
    proc = subprocess.Popen(
        [
            tools.ffmpeg_path(), "-v", "error", "-i", str(audio_path),
            "-vn", "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(SAMPLE_RATE),
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=tools.SUBPROCESS_FLAGS,
    )
    drain = tools.StderrDrain(proc.stderr)
    rms_parts: list[np.ndarray] = []
    leftover = np.zeros(0, dtype=np.float32)
    total_samples = 0
    assert proc.stdout is not None
    while True:
        buf = proc.stdout.read(chunk_bytes)
        if not buf:
            break
        usable = len(buf) - (len(buf) % 4)
        samples = np.frombuffer(buf[:usable], dtype=np.float32)
        total_samples += samples.size
        if leftover.size:
            samples = np.concatenate([leftover, samples])
        n = samples.size // window_size
        if n:
            block = samples[: n * window_size].reshape(n, window_size)
            rms_parts.append(np.sqrt(np.mean(np.square(block, dtype=np.float64), axis=1)).astype(np.float32))
        leftover = samples[n * window_size :].copy()
    proc.wait()
    stderr_text = drain.text()

    if proc.returncode != 0 or total_samples == 0:
        logger.warning("PCM decode failed for %s: %s", audio_path, stderr_text[-500:])
        if total_samples == 0:
            raise UnsupportedMediaError(
                "Couldn't analyze the audio in that video.",
                suggestion="The video may have no audio track.",
            )
    if leftover.size and not rms_parts:
        rms_parts.append(np.array([np.sqrt(np.mean(np.square(leftover)))], dtype=np.float32))

    rms = np.concatenate(rms_parts) if rms_parts else np.zeros(1, dtype=np.float32)
    return profile_from_rms(rms, window_seconds)


def profile_from_rms(rms: np.ndarray, window_seconds: float = WINDOW_SECONDS) -> EnergyProfile:
    rms = np.asarray(rms, dtype=np.float32)
    rms_db = 20 * np.log10(np.clip(rms, 1e-6, None))
    return EnergyProfile(
        window_seconds=window_seconds,
        rms=rms,
        rms_db=rms_db,
        mean_rms=float(np.mean(rms)),
        std_rms=float(np.std(rms)),
    )


def save_profile(profile: EnergyProfile, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"window_seconds": profile.window_seconds, "rms": [round(float(x), 6) for x in profile.rms]}),
        encoding="utf-8",
    )


def load_profile(path: Path) -> EnergyProfile | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return profile_from_rms(np.array(data["rms"], dtype=np.float32), float(data["window_seconds"]))
    except Exception:
        return None
