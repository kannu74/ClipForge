"""
Local speech-to-text via faster-whisper: word-level timestamps, sentence
segmentation, Hinglish-safe (task is always "transcribe", never "translate",
and language is auto-detected rather than forced -- forcing e.g. "hi" would
push English words toward Devanagari transliteration, which is exactly the
"don't translate Hinglish away" requirement in CLAUDE.md).

The engine is behind a small Protocol so the orchestration (file handling,
JSON I/O, API contract) is unit-testable without a downloaded model -- real
inference needs a one-time internet fetch of model weights the first time a
given model size is used.
"""
from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from app.config import settings
from app.errors import ExternalToolMissingError, InsufficientResourcesError
from app.logging_config import get_logger

logger = get_logger("transcription")


@dataclass
class Word:
    word: str
    start: float
    end: float
    probability: float | None = None


@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    edited: bool = False


@dataclass
class TranscriptResult:
    language: str | None
    model_size: str
    segments: list[Segment]


class TranscriptionEngine(Protocol):
    def transcribe(self, audio_path: Path, model_size: str) -> TranscriptResult: ...


ProgressFn = Callable[[float, str], None]

# Quality mode -> beam size. Beam search is the main speed/accuracy knob on CPU.
_BEAM_BY_QUALITY = {"fast": 1, "balanced": 5, "high_quality": 5, "maximum_quality": 5}


_GPU_FAILURE_MARKERS = (
    "cublas",
    "cudnn",
    "cuda",
    "gpu",
    "no kernel image",
    "out of memory",
)


def _is_gpu_runtime_failure(exc: Exception) -> bool:
    """True when an inference failure is about the GPU/CUDA runtime rather than
    the audio itself -- e.g. missing cuBLAS/cuDNN DLLs or exhausted VRAM."""
    return any(marker in str(exc).lower() for marker in _GPU_FAILURE_MARKERS)


class FasterWhisperEngine:
    """Real engine, backed by faster-whisper. Loads the model lazily so
    importing this module never requires internet or a downloaded model."""

    _model_cache: dict[tuple[str, str], object] = {}

    def _get_model(self, model_size: str, device: str = "auto"):
        cache_key = (model_size, device)
        if cache_key in self._model_cache:
            return self._model_cache[cache_key]
        try:
            from app.tools import register_gpu_dlls

            register_gpu_dlls()
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ExternalToolMissingError(
                "The local transcription engine (faster-whisper) isn't installed.",
                suggestion="Run `pip install -r requirements.txt` in the backend and try again.",
            ) from exc

        try:
            model = WhisperModel(model_size, device=device, compute_type="auto")
        except Exception as exc:
            msg = str(exc).lower()
            if "memory" in msg or "cuda" in msg:
                raise InsufficientResourcesError(
                    "The selected transcription model needs more GPU memory than is currently available.",
                    suggestion="Try a smaller model (tiny/base/small) or switch to CPU-only mode in settings.",
                    detail=str(exc),
                ) from exc
            raise ExternalToolMissingError(
                "Couldn't load the local transcription model.",
                suggestion=(
                    "The first time you use a given model size, ClipForge needs internet access to "
                    "download it once. After that it works fully offline. Check your connection and try again."
                ),
                detail=str(exc),
            ) from exc
        self._model_cache[cache_key] = model
        return model

    def _run(
        self,
        model,
        audio_path: Path,
        model_size: str,
        language: str | None = None,
        on_progress: ProgressFn | None = None,
    ) -> TranscriptResult:
        segments_iter, info = model.transcribe(
            str(audio_path),
            word_timestamps=True,
            vad_filter=True,
            task="transcribe",  # never "translate" -- Hinglish must stay Hinglish
            language=language or None,
            beam_size=_BEAM_BY_QUALITY.get(settings.quality_mode.value, 5),
            # Gaming audio has long stretches of music / game SFX with no speech;
            # not conditioning on previous text stops one hallucination from
            # snowballing into a repeated loop for the rest of the video.
            condition_on_previous_text=False,
            hallucination_silence_threshold=2.0,
            initial_prompt=settings.whisper_initial_prompt or None,
        )
        total = float(getattr(info, "duration", 0.0) or 0.0)
        if on_progress:
            lang = getattr(info, "language", None)
            on_progress(0.0, f"Transcribing (language detected: {lang or 'unknown'})...")
        segments: list[Segment] = []
        # faster-whisper is lazy: inference (and therefore any CUDA failure)
        # happens while iterating, not at model construction time.
        for i, seg in enumerate(segments_iter):
            words = [
                Word(word=w.word.strip(), start=w.start, end=w.end, probability=w.probability)
                for w in (seg.words or [])
                if w.word.strip()
            ]
            text = seg.text.strip()
            if not text:
                continue
            segments.append(Segment(id=len(segments), start=seg.start, end=seg.end, text=text, words=words))
            if on_progress and total > 0:
                on_progress(min(seg.end / total, 1.0), f"Transcribing... {_fmt(seg.end)} / {_fmt(total)}")
        return TranscriptResult(language=getattr(info, "language", None), model_size=model_size, segments=segments)

    def transcribe(
        self,
        audio_path: Path,
        model_size: str,
        language: str | None = None,
        on_progress: ProgressFn | None = None,
    ) -> TranscriptResult:
        device = settings.whisper_device
        if on_progress:
            on_progress(0.0, f"Loading speech model '{model_size}' (the first run downloads it once)...")
        try:
            model = self._get_model(model_size, device)
            return self._run(model, audio_path, model_size, language, on_progress)
        except Exception as exc:
            gpu_problem = isinstance(exc, InsufficientResourcesError) or _is_gpu_runtime_failure(exc)
            if device == "cpu" or not gpu_problem:
                raise
            # CLAUDE.md: never crash because the GPU path isn't usable -- fall
            # back to CPU and say why in plain language.
            logger.warning(
                "GPU transcription unavailable (%s). Falling back to CPU, which is slower "
                "but produces identical output.",
                exc,
            )
            self._model_cache.pop((model_size, device), None)
            cpu_size = model_size
            if settings.whisper_model_size == "auto" and model_size in _CPU_FRIENDLY_FALLBACK:
                # A large model that was auto-picked for the GPU would crawl on
                # CPU; switch to the CPU default rather than making the user wait hours.
                cpu_size = _CPU_FRIENDLY_FALLBACK[model_size]
            if on_progress:
                on_progress(
                    0.0,
                    "GPU unavailable for transcription -- continuing on CPU"
                    + (f" with the '{cpu_size}' model" if cpu_size != model_size else "")
                    + " (slower)...",
                )
            cpu_model = self._get_model(cpu_size, "cpu")
            return self._run(cpu_model, audio_path, cpu_size, language, on_progress)


_CPU_FRIENDLY_FALLBACK = {"large-v3": "small", "large-v3-turbo": "small", "large-v2": "small", "medium": "small"}


def resolve_model_size(requested: str | None) -> str:
    """Turn "auto" (or nothing) into a concrete model for this machine."""
    size = (requested or settings.whisper_model_size or "auto").strip()
    if size != "auto":
        return size
    if settings.whisper_device == "cpu":
        return "small"
    try:
        from app.hardware import _detect_gpu

        gpu = _detect_gpu()
        if gpu.available and (gpu.vram_total_mb or 0) >= 6000:
            return "large-v3-turbo"
    except Exception:  # pragma: no cover
        pass
    return "small"


def _fmt(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _accepts_options(engine) -> bool:
    try:
        params = inspect.signature(engine.transcribe).parameters
    except (TypeError, ValueError):
        return False
    return "on_progress" in params or any(p.kind == p.VAR_KEYWORD for p in params.values())


def run_transcription(
    video_path: Path,
    audio_scratch_path: Path,
    model_size: str | None = None,
    engine: TranscriptionEngine | None = None,
    *,
    start: float | None = None,
    end: float | None = None,
    language: str | None = None,
    on_progress: ProgressFn | None = None,
) -> TranscriptResult:
    """Transcribe `video_path` (optionally only [start, end) seconds). All
    returned timestamps are absolute times in the source video."""
    from app import media

    model_size = resolve_model_size(model_size)
    engine = engine or FasterWhisperEngine()
    language = language if language is not None else (settings.whisper_language or None)

    if on_progress:
        on_progress(0.0, "Extracting audio...")
    media.extract_audio(video_path, audio_scratch_path, start=start, end=end)
    offset = float(start or 0.0)
    try:
        started = time.time()
        if _accepts_options(engine):
            result = engine.transcribe(audio_scratch_path, model_size, language=language, on_progress=on_progress)
        else:
            result = engine.transcribe(audio_scratch_path, model_size)
        if offset:
            for seg in result.segments:
                seg.start = round(seg.start + offset, 3)
                seg.end = round(seg.end + offset, 3)
                for w in seg.words:
                    w.start = round(w.start + offset, 3)
                    w.end = round(w.end + offset, 3)
        logger.info(
            "Transcribed %s in %.1fs (%d segments, language=%s, model=%s, range=%s-%s)",
            video_path.name,
            time.time() - started,
            len(result.segments),
            result.language,
            model_size,
            start,
            end,
        )
        return result
    finally:
        audio_scratch_path.unlink(missing_ok=True)


def to_dict(
    project_id: str,
    result: TranscriptResult,
    created_at: str,
    range_start: float | None = None,
    range_end: float | None = None,
) -> dict:
    return {
        "project_id": project_id,
        "language": result.language,
        "model_size": result.model_size,
        "created_at": created_at,
        "range_start": range_start,
        "range_end": range_end,
        "segments": [
            {
                "id": seg.id,
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "edited": seg.edited,
                "words": [
                    {"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
                    for w in seg.words
                ],
            }
            for seg in result.segments
        ],
    }
