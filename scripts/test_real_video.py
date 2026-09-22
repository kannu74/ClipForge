"""
One-shot real-video pipeline check for ClipForge.

Why this exists: the sandboxed environment ClipForge was built in has
youtube.com and huggingface.co blocked at the network level, so the actual
download + transcription + moment-detection pipeline has never run against
real content. This script runs the exact same backend modules the API uses
(app.media, app.transcription, app.moments) against a real YouTube video on
YOUR machine, which has normal internet access, and prints a human-readable
report so you can judge quality directly -- per the project's own rule that
human evaluation is the final authority, not a model's self-reported score.

Usage (from the backend/ directory, inside its venv):
    python ../scripts/test_real_video.py "https://www.youtube.com/watch?v=VIDEO_ID"

Options:
    --seconds N       Only process the first N seconds (default: 180).
                       Use --seconds 0 to process the full video.
    --model SIZE       Whisper model size: tiny|base|small|medium|large-v3
                       (default: small -- base/tiny are noticeably worse at
                       Hinglish/accented speech, per DEVELOPMENT_PROGRESS.md).
    --content-type T   gaming|funny_gaming|horror_gaming|reaction|comedy|
                        commentary|storytelling|general_creator
                        (default: horror_gaming)

The first run will download Whisper model weights from Hugging Face (one
time, needs internet); after that it's fully offline for that model size.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import media  # noqa: E402
from app.audio_analysis import compute_energy_profile  # noqa: E402
from app.moments import detect_moments  # noqa: E402
from app.transcription import FasterWhisperEngine, run_transcription  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--seconds", type=int, default=180, help="Only process the first N seconds (0 = full video)")
    parser.add_argument("--model", default="small", help="Whisper model size")
    parser.add_argument("--content-type", default="horror_gaming", help="Content type for moment detection")
    args = parser.parse_args()

    from app import youtube

    work_dir = Path(tempfile.mkdtemp(prefix="clipforge_real_video_"))
    print(f"== Downloading (first {args.seconds}s)" if args.seconds else "== Downloading (full video)", flush=True)

    def progress(frac: float, msg: str) -> None:
        print(f"  {msg}", flush=True)

    section = (0.0, float(args.seconds)) if args.seconds else None
    video_path, info = youtube.download(args.url, work_dir, on_progress=progress, section=section)
    print(f"Title: {info.get('title')}")
    print(f"Channel: {info.get('uploader')}")
    print(f"Full video duration: {info.get('duration')}s")

    print("\n== Metadata (ffprobe)", flush=True)
    meta = media.probe(video_path)
    for k, v in meta.to_dict().items():
        print(f"  {k}: {v}")

    print(f"\n== Transcribing with model='{args.model}' (this can take a while on CPU)...", flush=True)
    audio_scratch = work_dir / "_audio.wav"
    result = run_transcription(video_path, audio_scratch, model_size=args.model, engine=FasterWhisperEngine())
    print(f"Detected language: {result.language}")
    print(f"Segments: {len(result.segments)}\n")
    for seg in result.segments:
        print(f"  [{seg.start:6.1f} - {seg.end:6.1f}] {seg.text}")

    print("\n== Detecting moments...", flush=True)
    audio_for_energy = work_dir / "_audio_energy.wav"
    media.extract_audio(video_path, audio_for_energy)
    energy = compute_energy_profile(audio_for_energy)
    # Same sentence-level units the app uses.
    from app.transcription import to_dict
    from app.units import units_from_transcript

    units = units_from_transcript(to_dict("cli", result, ""))
    moments, ollama_used = detect_moments(args.content_type, units, energy)
    print(f"Ollama enrichment used: {ollama_used}")
    print(f"Candidate moments: {len(moments)}\n")
    for m in moments:
        print(f"  [{m.category:9s}] {m.start:6.1f}-{m.end:6.1f} (score {m.score:.2f})  {m.reason}")
        print(f"    \"{m.transcript_excerpt}\"\n")

    print(f"\nWorking files kept at: {work_dir}")


if __name__ == "__main__":
    main()
