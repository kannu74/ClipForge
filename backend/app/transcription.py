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

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

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


class FasterWhisperEngine:
    """Real engine, backed by faster-whisper. Loads the model lazily so
    importing this module never requires internet or a downloaded model."""

    _model_cache: dict[str, object] = {}

    def _get_model(self, model_size: str):
        if model_size in self._model_cache:
            return self._model_cache[model_size]
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ExternalToolMissingError(
                "The local transcription engine (faster-whisper) isn't installed.",
                suggestion="Run `pip install -r requirements.txt` in the backend and try again.",
            ) from exc

        try:
            model = WhisperModel(model_size, device="auto", compute_type="auto")
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
        self._model_cache[model_size] = model
        return model

    def transcribe(self, audio_path: Path, model_size: str) -> TranscriptResult:
        model = self._get_model(model_size)
        segments_iter, info = model.transcribe(
            str(audio_path),
            word_timestamps=True,
            vad_filter=True,
            task="transcribe",  # never "translate" -- Hinglish must stay Hinglish
        )
        segments: list[Segment] = []
        for i, seg in enumerate(segments_iter):
            words = [
                Word(word=w.word.strip(), start=w.start, end=w.end, probability=w.probability)
                for w in (seg.words or [])
            ]
            segments.append(Segment(id=i, start=seg.start, end=seg.end, text=seg.text.strip(), words=words))
        return TranscriptResult(language=getattr(info, "language", None), model_size=model_size, segments=segments)


def run_transcription(
    video_path: Path,
    audio_scratch_path: Path,
    model_size: str | None = None,
    engine: TranscriptionEngine | None = None,
) -> TranscriptResult:
    from app import media

    model_size = model_size or settings.whisper_model_size
    engine = engine or FasterWhisperEngine()

    media.extract_audio(video_path, audio_scratch_path)
    try:
        started = time.time()
        result = engine.transcribe(audio_scratch_path, model_size)
        logger.info(
            "Transcribed %s in %.1fs (%d segments, language=%s, model=%s)",
            video_path.name,
            time.time() - started,
            len(result.segments),
            result.language,
            model_size,
        )
        return result
    finally:
        audio_scratch_path.unlink(missing_ok=True)


def to_dict(project_id: str, result: TranscriptResult, created_at: str) -> dict:
    return {
        "project_id": project_id,
        "language": result.language,
        "model_size": result.model_size,
        "created_at": created_at,
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
