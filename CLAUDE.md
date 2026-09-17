# CLAUDE.md — Working agreement for ClipForge

This file is the condensed, load-bearing version of the full product brief. Read this and `DEVELOPMENT_PROGRESS.md` before making any non-trivial change. The full original brief (all 54 sections) lives in `docs/PRODUCT_BRIEF.md` — refer back to it for details this file compresses.

## The one rule that overrides everything else

**Clip quality is the product.** The test for every generated clip is: "Would a real content creator actually publish this?" Not "did the model return timestamps," not "did the code run," not "did a model score it 95/100." If a change doesn't make clips better (or the workflow to get good clips faster), it is low priority — no matter how interesting it is to build.

Do not:
- Add features that don't improve clip quality, boundary quality, transcription quality, caption quality, or reframing quality.
- Mark a phase "complete" because the code runs. It's complete when real output has been inspected and is meaningfully better.
- Fake AI results, stub a feature behind a working-looking button, or leave dead UI once a phase is actually being implemented. If something isn't built yet, the UI must say so.
- Rewrite working code unnecessarily. Inspect before changing.

## Priority order (when in doubt, work top-down)

1. Clip quality (does the selected moment deserve to be a clip)
2. Clip boundary quality (does it start/end in a natural place)
3. Transcription quality (including Hinglish — never translate it away)
4. Caption quality (readable, well-timed, well-broken)
5. Semantic understanding (hook/context/event/payoff/clean ending)
6. Reframing quality (9:16 crop that doesn't lose the action)
7. Rendering reliability
8. Quality control (automated QC before a clip reaches the user)
9. Creator review workflow
10. Performance/caching
11. UI polish
12. Everything else

## Local-first constraints

- No video/audio/transcript content is sent to an external service by default. The only network call that's expected by default is fetching a YouTube video the user explicitly pasted a URL for.
- Transcription: local (faster-whisper). LLM reasoning (moment understanding, ranking rationale, caption cleanup): local via Ollama, model configurable — never hard-code a single model name into the pipeline logic. Read the model from config/settings.
- Hardware awareness is mandatory: detect CPU/RAM/GPU/VRAM/CUDA at startup, expose it to the UI, and never crash because a model doesn't fit in VRAM — fall back to CPU or a smaller model and tell the user why in plain language (see Error handling below).
- Long videos (1-3+ hours) must be processed without loading the whole file into memory, and intermediate results (transcript, detected moments, etc.) must be cached so a failure partway through doesn't force a full restart.

## Error handling

Errors shown to the user must be actionable and in plain language. Never surface a raw stack trace or a message like `CUDA error: invalid argument`. Instead: "The selected AI model needs more GPU memory than is available. Try Balanced mode or a smaller model." Backend errors should be raised as the typed exceptions in `backend/app/errors.py` so the global handler can translate them consistently.

## Architecture reference

- `backend/` — FastAPI, Python 3.10+. SQLite for project/clip metadata (`backend/app/db.py`). Project media/artifacts live on disk under `backend/data/projects/<id>/`, never in git.
- `frontend/` — React + TypeScript + Vite + Tailwind, dark mode by default, talks to the backend over REST (and WebSocket once processing/progress streaming exists).
- Config: `backend/app/config.py` (pydantic-settings, reads `.env`). Add new tunables there, not as hard-coded constants scattered through the pipeline.
- Logging: `backend/app/logging_config.py`. Use it, don't `print()`.

## Development environment note

Day-to-day coding on this repo currently happens through a sandboxed build shell that has **no GPU and ~4GB RAM** — it is not representative of the machine ClipForge actually runs on. That means:
- CPU code paths (transcription with small Whisper models, etc.) can be smoke-tested here.
- GPU code paths, large models, and Ollama itself cannot be exercised here — they need to be verified on the real machine (or reported by Akshar) before a phase touching them is called done.
- Say explicitly in `DEVELOPMENT_PROGRESS.md` when something is "implemented but not yet verified on real hardware."

## Testing discipline

- Test with real creator-style videos (gaming, horror gameplay, Hinglish/Hindi speech, fast speech, loud reactions), not just synthetic clips, as soon as a phase produces user-facing output.
- Before saying a phase is done: implementation works, tests pass, it's been run against a real input, output was actually inspected (watched/read, not just "no exception"), and known problems are written down — not silently left for later.
- Update `DEVELOPMENT_PROGRESS.md` after every meaningful milestone, not just at phase boundaries.

## Phase order (do not skip ahead)

0 Foundation → 1 Ingestion → 2 Transcription → 3 Moment detection → 4 Ranking → 5 Boundary optimization → 6 Hinglish captions → 7 Smart reframing/editing → 8 Presets → 9 Rendering → 10 Automated QC → 11 Creator review → 12 Personalization → 13 DaVinci workflow → 14 Benchmarking (ongoing).

Phases 0-6 (get a genuinely good clip out of the pipeline, transcribed and captioned correctly) matter far more than 7-13. A beautiful UI around mediocre clips is not success.
