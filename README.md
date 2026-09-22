# ClipForge

Local-first AI clipping for creators — an OpusClip-style tool that runs entirely on your own computer, built for gaming, horror, comedy and reaction videos, and Hinglish / Hindi / English speech.

Paste a YouTube link or upload a video → ClipForge transcribes it, finds the best moments, cuts them at natural start/end points, burns in word-by-word captions, reframes to 9:16 (with a facecam split for gaming), and gives you ready-to-post MP4s. Every clip can be trimmed, re-captioned and re-framed afterwards.

Nothing is uploaded anywhere. The only network use is downloading a YouTube video you paste, and a one-time download of the speech model.

## Quick start (Windows)

1. Install **Python 3.12** from [python.org](https://www.python.org/downloads/) — tick **“Add python.exe to PATH”** in the installer. (3.10 and 3.11 also work; 3.13+ doesn't yet.)
2. Double-click **`ClipForge.bat`**.
   - The first run sets everything up (a few minutes: it installs the components, including FFmpeg and the YouTube downloader).
   - Your browser opens at `http://127.0.0.1:8000`. Keep the black ClipForge window open while you work; close it to stop.
3. Paste a YouTube link (or upload a file), pick the video type, press **Get clips**.

The first transcription also downloads the speech model once (~0.5 GB for the default). After that everything works offline, apart from YouTube downloads.

**NVIDIA GPU?** Run `scripts\enable-gpu.bat` once (downloads ~1.5 GB of NVIDIA libraries). Transcription gets much faster, and ClipForge picks a more accurate model automatically. If the GPU ever fails, it falls back to the CPU on its own.

On macOS/Linux: `cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python run.py`.

## What you get

- **Input:** YouTube links (videos, lives, shorts) or any video file (MP4, MOV, MKV, WEBM, AVI, …). You can process just part of a long stream; for YouTube, only that part is downloaded.
- **Clip finding:** audio-energy spikes combined with Hinglish/English reaction and gaming vocabulary, tuned per content type (gaming, horror, funny, reaction, comedy, commentary, storytelling). Clips are fitted to your chosen length (10–20s, 20–35s, 30–60s, 60–90s or custom) with setup before the peak and the payoff after it. Cuts land between words, never mid-word. Each clip gets a 1–99 score, a title and a plain-language “why this clip”. If there aren't enough strong moments, backup picks are clearly marked — nothing is padded silently.
- **Captions:** six styles — Bold Pop, Karaoke, Clean, Boxed, Horror, Neon — with word-by-word highlighting, hype-word colouring, position, size, words per line, colours and UPPERCASE. Hindi in Devanagari renders correctly. An optional **Roman Hinglish** mode turns “भाई ये क्या है” into “bhai ye kya hai” (transliteration only — words are never translated). An SRT file comes with every clip.
- **Framing:** 9:16, 1:1, 4:5 or 16:9.
  - **Auto** picks a facecam split, face tracking or a safe full frame.
  - **Facecam split:** webcam on top, gameplay below, captions on the seam.
  - **Follow face:** a smooth crop that follows the speaker.
  - **Full frame** over a blurred background.
  - **Crop** and **Letterbox**.
  - You can mark the facecam area yourself.
- **Editing:** trim on a timeline (±0.2s / ±1s nudges or drag handles), fix caption words, change caption style or framing per clip, retitle, cut your own clips from the source, then re-render.
- **Output:** H.264/AAC MP4s with loudness normalised for Shorts/Reels/TikTok (-14 LUFS) and 1080p or 720p output. Downloads per clip or all at once as a zip. An automatic quality check flags wrong length, silent audio or black frames.

## Settings

Advanced settings live in `backend/.env` (created on first run from `.env.example`):

| Setting | What it does |
|---|---|
| `CLIPFORGE_WHISPER_MODEL_SIZE` | `auto` (default) · `small` · `medium` · `large-v3-turbo` · `large-v3`. Also selectable per project in the UI. |
| `CLIPFORGE_WHISPER_DEVICE` | `auto` / `cuda` / `cpu` |
| `CLIPFORGE_WHISPER_INITIAL_PROMPT` | Optional: game names or slang, to help spelling |
| `CLIPFORGE_YOUTUBE_COOKIES_BROWSER` | `firefox` / `edge` / `chrome`: use your browser's YouTube login if YouTube asks to “confirm you're not a bot” |
| `CLIPFORGE_VIDEO_ENCODER` | `auto` (NVIDIA NVENC if available, else x264) / `x264` / `nvenc` |
| `CLIPFORGE_OLLAMA_HOST`, `CLIPFORGE_OLLAMA_MODEL` | Optional local LLM (Ollama) for better titles and moment checks. ClipForge works fully without it. |
| `CLIPFORGE_DATA_DIR` | Where projects, videos and clips are stored (default `backend/data`) |

## Troubleshooting

- **YouTube download fails:** close ClipForge and run `ClipForge.bat` again. If the component list changed it reinstalls, and `yt-dlp` updates often. If YouTube asks for a sign-in check, set `CLIPFORGE_YOUTUBE_COOKIES_BROWSER`. You can always download the video yourself and upload the file.
- **Slow transcription:** that is normal on CPU (roughly real time). Use “Only use part of the video”, pick “Fast” accuracy, or enable the GPU.
- **Something failed:** the app shows a plain-language reason. Technical details are in `backend/data/logs/clipforge.log`.
- **Port busy:** ClipForge uses the next free port automatically. The window shows the address.

## For developers

- Backend: FastAPI + SQLite in `backend/app`. `pipeline.py` holds the end-to-end steps and `jobs.py` the background job queue. `captions.py`, `reframe.py` and `render.py` form the video pipeline. Tests: `cd backend && python -m pytest -q`.
- Frontend: React + TypeScript + Vite + Tailwind in `frontend/`. `npm run build` writes to `backend/app/static`, which the backend serves, so end users never need Node. `scripts/start-dev.bat` (or `npm run dev`) gives hot reload with an `/api` proxy.
- Working agreement and roadmap: `CLAUDE.md`. Honest per-phase status: `DEVELOPMENT_PROGRESS.md`.

## Licences of bundled assets

- Caption fonts (Mukta, Hind, Anton, Bebas Neue): SIL Open Font License — `backend/app/assets/fonts/OFL.txt`.
- YuNet face detector (OpenCV Zoo): MIT — `backend/app/assets/models/YUNET_LICENSE.txt`.
- The test face image is a public-domain NASA photo.
