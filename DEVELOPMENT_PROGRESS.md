# ClipForge — Development Progress

Read this before starting any work. Update it after every meaningful milestone, not just at phase boundaries. See `CLAUDE.md` for the working agreement and `docs/PRODUCT_BRIEF.md` for the full original spec.

Last updated: 2026-09-17

## Phase status

| Phase | Status |
|---|---|
| 0 — Foundation | **COMPLETE** |
| 1 — Video ingestion | NOT STARTED |
| 2 — Local transcription | NOT STARTED |
| 3 — Intelligent moment detection | NOT STARTED |
| 4 — Clip ranking | NOT STARTED |
| 5 — Boundary optimization | NOT STARTED |
| 6 — Hinglish captions | NOT STARTED |
| 7 — Smart video editing/reframing | NOT STARTED |
| 8 — Presets | NOT STARTED |
| 9 — Rendering | NOT STARTED |
| 10 — Automated QC | NOT STARTED |
| 11 — Creator review | NOT STARTED |
| 12 — Personalization | NOT STARTED |
| 13 — DaVinci workflow | NOT STARTED |
| 14 — Quality benchmarking | NOT STARTED (ongoing once clips exist) |

---

## Phase 0 — Foundation: COMPLETE

### What was implemented

**Backend** (`backend/`, FastAPI + Python 3.10+):
- `app/config.py` — pydantic-settings config, reads `.env`, exposes quality mode, data dir, Ollama host/model, Whisper model size. Nothing pipeline-related is hard-coded elsewhere.
- `app/logging_config.py` — structured logging to stdout + rotating file (`data/logs/clipforge.log`).
- `app/errors.py` — typed `ClipForgeError` subclasses (`ValidationFailedError`, `NotFoundError`, `UnsupportedMediaError`, `ExternalToolMissingError`, `InsufficientResourcesError`) + global exception handlers that return plain-language JSON, never a raw stack trace or technical error string.
- `app/hardware.py` — detects CPU cores, RAM, GPU/VRAM/CUDA (via `nvidia-smi`, falling back to `torch.cuda` if installed), ffmpeg presence/version, and Ollama reachability + installed model list. Recommends a quality mode (fast/balanced/high_quality/maximum_quality) from what it finds. Never raises — a detection failure just means "unavailable", not a crash.
- `app/db.py` — SQLite project metadata store (plain `sqlite3`, no ORM — schema is small enough that an ORM would be premature).
- `app/storage.py` — per-project on-disk layout: `data/projects/<id>/{source,transcript,moments,clips,renders}/` + a human-readable `project.json` manifest.
- `app/routers/projects.py` — project CRUD: `POST/GET /api/projects`, `GET/DELETE /api/projects/{id}`.
- `app/routers/system.py` — `GET /api/system/health`, `GET /api/system/hardware`.
- `tests/` — pytest suite (6 tests) covering health, hardware report shape, project create/list/get/delete, and friendly-error-on-missing-project. All passing.

**Frontend** (`frontend/`, React + TypeScript + Vite + Tailwind, dark mode):
- App shell (`App.tsx`) with a top bar showing a live hardware badge (GPU/CPU, recommended quality mode, ffmpeg/Ollama status) pulled from `/api/system/hardware`.
- `pages/Home.tsx` — project list (empty state + grid), "New project" flow.
- `components/NewProjectModal.tsx` — name + content-type selection, calls the real create-project API, surfaces backend errors (including the "backend unreachable" case) in plain language.
- `pages/ProjectDetail.tsx` — loads a real project by id. Explicitly says video ingestion isn't built yet rather than showing a fake/broken upload UI (per the no-fake-functionality rule).
- `lib/api.ts` / `lib/types.ts` — typed API client, single source of truth for the backend contract.

**Docs**: `README.md` (setup/run instructions), `CLAUDE.md` (condensed working agreement + priority order), `docs/PRODUCT_BRIEF.md` (full original spec, verbatim), this file.

**Repo**: git initialized, `.gitignore` excludes `.venv/`, `node_modules/`, `data/` (project media/DB — never committed), logs, env files.

### What works (verified, not assumed)

- Backend: `pip install -r requirements.txt` succeeds cleanly. `pytest` → 6/6 passing.
- Backend actually started with `uvicorn` and hit over real HTTP with `curl`:
  - `GET /api/system/health` → `{"status":"ok"}`
  - `GET /api/system/hardware` → correct report for this machine (2 logical cores, ~3.9GB RAM, no GPU, ffmpeg 4.4.2 found, Ollama not reachable — all accurate for this environment)
  - `POST /api/projects` → creates a row in SQLite **and** the on-disk project directory scaffold (`source/`, `transcript/`, `moments/`, `clips/`, `renders/`, `project.json`), confirmed by inspecting the filesystem and querying the DB directly.
  - `GET /api/projects` → returns the created project.
- Frontend: `npm install` clean, `npm run build` (tsc + vite) compiles with zero errors, dev server (`vite`) starts and serves the real module graph (index.html, main.tsx, React/Router deps resolving) over HTTP, confirmed with `curl`.

### What was NOT verified (known limitation of the current dev environment)

Day-to-day coding on this repo currently happens through a sandboxed build shell with **2 CPU cores, ~4GB RAM, and no GPU** (confirmed via `nvidia-smi` absent). It is not representative of Akshar's real machine. As a result:
- The UI has **not** been visually verified in an actual browser — only server-level HTTP checks (correct HTML, correct module resolution, no build errors) were done. Akshar should run `scripts/start-dev.bat` (or the two dev commands from README) and confirm it actually looks/works right in a browser.
- GPU detection code path is implemented but untested against a real NVIDIA GPU/CUDA setup.
- Ollama integration point exists (`config.py` has `ollama_host`/`ollama_model`, `hardware.py` detects reachability) but no actual LLM call has been wired up yet or tested against Akshar's installed model — that starts in Phase 3/4 (moment detection/ranking).

### Known bugs / issues

None currently open. (One caught-and-fixed during this phase: FastAPI raised `AssertionError: Status code 204 must not have a response body` on the delete-project route until `response_model=None` was added — fixed and verified via passing tests.)

### Next tasks (Phase 1 — Video ingestion)

1. Local file upload endpoint (multipart) + storage into `data/projects/<id>/source/`.
2. YouTube URL input: validation, metadata fetch, local download (yt-dlp), respecting access restrictions (no DRM/private-video bypassing).
3. ffprobe-based metadata extraction: duration, resolution, FPS, codecs, audio tracks, file size, aspect ratio.
4. Project status transitions (`created` → `ingesting` → `ready`) reflected in the UI.
5. Basic video preview in the frontend once a source exists.
6. Ask Akshar for (or source) a real test video — ideally a Hinglish gaming clip — before Phase 2, since transcription quality can't be judged on synthetic input.
