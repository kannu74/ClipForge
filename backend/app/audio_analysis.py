"""
Deterministic audio-energy analysis. No ML model, no network -- just decode
PCM via ffmpeg and compute short-time RMS loudness over time with numpy.
This is the non-LLM signal moment detection leans on (spec: "do not rely
solely on an LLM's subjective score; use deterministic information where
possible"), and it works identically whether or not Ollama is reachable.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

import numpy as np

from app.errors import ExternalToolMissingError, UnsupportedMediaError
from app.logging_config import get_logger

logger = get_logger("audio_analysis")

SAMPLE_RATE = 16000
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
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ExternalToolMissingError(
            "FFmpeg isn't installed or isn't on PATH.",
            suggestion="Install FFmpeg and make sure it's on your system PATH, then try again.",
        )

    proc = subprocess.run(
        [
            ffmpeg, "-v", "error", "-i", str(audio_path),
            "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(SAMPLE_RATE),
            "pipe:1",
        ],
        capture_output=True,
        timeout=600,
    )
    if proc.returncode != 0 or not proc.stdout:
        logger.warning("PCM decode failed for %s: %s", audio_path, proc.stderr[:500])
        raise UnsupportedMediaError("Couldn't analyze the audio in that video.")

    samples = np.frombuffer(proc.stdout, dtype=np.float32)
    if samples.size == 0:
        raise UnsupportedMediaError("That video's audio track appears to be empty.")

    window_size = max(1, int(SAMPLE_RATE * window_seconds))
    n_windows = max(1, samples.size // window_size)
    trimmed = samples[: n_windows * window_size].reshape(n_windows, window_size)
    rms = np.sqrt(np.mean(np.square(trimmed), axis=1))
    rms_db = 20 * np.log10(np.clip(rms, 1e-6, None))

    return EnergyProfile(
        window_seconds=window_seconds,
        rms=rms,
        rms_db=rms_db,
        mean_rms=float(np.mean(rms)),
        std_rms=float(np.std(rms)),
    )
