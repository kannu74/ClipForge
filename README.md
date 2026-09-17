# ClipForge

A local-first AI video clipping tool for gaming, commentary, reactions, comedy, horror-gaming and Hinglish/Hindi/English creator content. Turns long-form gameplay or YouTube videos into curated, captioned, vertically-reframed short clips — with the whole AI pipeline (transcription, moment detection, ranking, captioning) running on your own machine by default.

**Status:** Phase 0 (Foundation) — see `DEVELOPMENT_PROGRESS.md` for the authoritative, up-to-date phase status.

## Why local-first

ClipForge does not require a cloud AI subscription. Transcription, content understanding, moment detection/ranking, and caption generation are designed to run against local models (faster-whisper for speech-to-text, Ollama for LLM reasoning). The only network access needed is to fetch a YouTube video when you give it a URL, or to download models the first time. After that, it works offline.

## Architecture

```
clipper/
  backend/     FastAPI app (Python) — API, video processing, AI pipeline, SQLite project storage
  frontend/    React + Vite + TypeScript + Tailwind — local web UI (dark mode)
  docs/        Design notes, phase specs
  scripts/     Setup/dev launch scripts
  DEVELOPMENT_PROGRESS.md   Live phase-by-phase status. Read this before starting work.
  CLAUDE.md    Working agreement / conventions for AI-assisted development on this repo.
```

The backend and frontend are two local processes talking over HTTP/WebSocket on localhost. Nothing leaves your machine except an optional YouTube fetch.

## Requirements

- Python 3.10+
- Node.js 18+
- FFmpeg on PATH (`ffmpeg -version` should work)
- [Ollama](https://ollama.com) installed and at least one model pulled (e.g. `ollama pull llama3.1`) — used for content understanding / moment ranking. ClipForge will run without it but LLM-assisted features will be unavailable until it's configured.
- Optional: NVIDIA GPU + CUDA for faster transcription/inference. ClipForge detects your hardware and falls back to CPU automatically — it will not crash without a GPU, just run slower.

## Getting started (development)

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Backend runs at `http://localhost:8000`. Interactive API docs at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Frontend runs at `http://localhost:5173` and talks to the backend at the URL in `.env`.

### One-shot (Windows)

`scripts/start-dev.bat` launches both in separate windows once the above setup has been done once.

## Project data

Each project's source video, transcript, detected moments, generated clips, and exports live under `backend/data/projects/<project_id>/`. This directory is intentionally git-ignored — it's your media, not source code.

## Development philosophy

Read `CLAUDE.md` before making changes. In short: clip quality is the product. Do not add features that don't move clip quality, boundary quality, transcription quality, or caption quality forward. No placeholder AI results once a phase is being implemented — if something isn't real yet, it's marked as such in the UI and in `DEVELOPMENT_PROGRESS.md`, not faked.
