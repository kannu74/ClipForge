# ClipForge — Development Progress

Read this before starting any work. Update it after every meaningful milestone. See `CLAUDE.md` for the working agreement and `docs/PRODUCT_BRIEF.md` for the full original spec.

Last updated: 2026-09-23

## Where things stand (short version)

ClipForge is now a complete, usable app: double-click `ClipForge.bat` → paste a YouTube link or upload a video → get rendered 9:16 clips with burned-in captions and facecam-aware framing → trim, re-caption, re-frame, and download them. Every stage runs in the background with live progress.

**Verified here:**
- Upload, transcript handling, moment detection, ranking, duration fitting, captions, reframing, rendering, QC, editing and downloads all work end-to-end, through the real API and the real UI (driven with Playwright).
- The rendered MP4s were inspected frame by frame.
- 78 automated tests pass on Python 3.10 and 3.11.

**Not verifiable here, and the most important thing to check next:**
- real Whisper transcription quality (especially Hinglish);
- real YouTube downloads;
- the Windows launcher on the real PC;
- GPU/NVENC paths.

The sandboxes this was built in block youtube.com and huggingface.co and have no GPU or Windows. The code for each of these is written defensively with fallbacks, but "written defensively" is not "verified" — see the per-phase caveats below.

## Phase status

| Phase | Status |
|---|---|
| 0 — Foundation | **COMPLETE** |
| 1 — Video ingestion | **IMPLEMENTED** — upload verified end-to-end; YouTube path rebuilt (latest yt-dlp + JS runtime, section download) but **never run against real YouTube** |
| 2 — Local transcription | **IMPLEMENTED, orchestration verified — ASR quality NOT verified** |
| 3 — Moment detection | **IMPLEMENTED, verified on crafted signals — needs real-video judgment** |
| 4 — Clip ranking | **IMPLEMENTED, verified on crafted signals — weights unvalidated on real content** |
| 5 — Boundary optimization | **IMPLEMENTED (reworked: sentence units + duration fitting), verified on crafted signals** |
| 6 — Hinglish captions | **IMPLEMENTED, renders inspected visually (Latin + Devanagari) — needs real-speech judgment** |
| 7 — Smart reframing | **IMPLEMENTED, split/blur/crop/letterbox inspected visually; face tracking unit-tested — needs real footage** |
| 8 — Presets | **IMPLEMENTED** — 5 built-in presets (Horror Shorts, Gaming Highlights, Funny Moments, Podcast/Talking, Hinglish Reaction) + save/delete your own; last-used settings remembered |
| 9 — Rendering | **IMPLEMENTED, verified** (x264). NVENC path untested (no GPU here) |
| 10 — Automated QC | **IMPLEMENTED, verified** (duration, resolution, audio present/silent, black frames) |
| 11 — Creator review | **IMPLEMENTED, verified via API tests + UI screenshots** |
| 12 — Personalization | NOT STARTED |
| 13 — DaVinci workflow | NOT STARTED (SRT export exists; no XML/EDL yet) |
| 14 — Quality benchmarking | NOT STARTED — needs real videos + Akshar's judgment |

---

## First real-world run — checklist for Akshar

1. Double-click `ClipForge.bat`. First run installs the components (a few minutes). The existing `backend/.venv-win` is reused and upgraded.
   - **If it fails:** copy the window's text.
2. In the browser, paste your YouTube link (e.g. the horror video you shared) and choose **Horror gaming**.
   - **If the download fails:** try `CLIPFORGE_YOUTUBE_COOKIES_BROWSER=firefox` in `backend/.env`, or upload the file instead.
3. Watch the transcription step. The first run downloads the speech model once.
   - The Transcript tab shows exactly what Whisper heard. Is the Hinglish right? Did it write Hindi in Devanagari or Roman?
4. Judge the clips honestly. **This is the real quality gate for Phases 2–7:**
   - Did it pick the moments you would pick?
   - Do the clips start and end naturally?
   - Are the captions readable and well-timed?
   - Did the facecam split frame your webcam correctly? If not, mark the facecam area in a clip's **Framing** tab.
5. If you have an NVIDIA GPU, run `scripts\enable-gpu.bat`, restart, and compare transcription speed.

Send back what's wrong. That feedback is what moves Phases 2–7 from "implemented" to "good".

---

## Phase 0 — Foundation: COMPLETE

Config, logging, typed plain-language errors, hardware detection, SQLite project storage, project CRUD, frontend shell. Unchanged in substance; see git history.

## Phase 1 — Ingestion: IMPLEMENTED

**Upload** (verified):
- Runs in a worker thread, so a multi-GB upload doesn't freeze polling.
- Probes with ffprobe when present, otherwise PyAV. The bundled FFmpeg has no ffprobe, and the PyAV path handles phone rotation.
- Non-browser formats (MKV/AVI/HEVC…) get an automatic MP4 preview copy for the editor. Tested with MKV.
- `/media` supports HTTP Range, so the browser can seek.

**YouTube** (NOT verified against real YouTube):
- `yt-dlp[default]` (latest) with the `deno` JS runtime from pip, which yt-dlp now needs for YouTube, plus the bundled FFmpeg for merging.
- Prefers H.264 up to 1080p and reports download progress.
- Plain-language errors, with a cookies-from-browser setting for "confirm you're not a bot" checks.
- If a range is set, **only that section is downloaded**. If the section download fails, it falls back to the full video.
- Verified: the options are accepted by yt-dlp, the JS runtime is detected, and URL parsing covers watch/shorts/live/youtu.be/m./music. links.

## Phase 2 — Transcription: IMPLEMENTED — ASR quality NOT verified

**Implemented:**
- faster-whisper 1.2.1, `task="transcribe"` (never translate), word timestamps and VAD.
- `condition_on_previous_text=False` and `hallucination_silence_threshold`, to stop loops on long silent/music stretches in gaming audio.
- Progress reporting; range-limited transcription with absolute timestamps.
- Model `auto`: `large-v3-turbo` on an NVIDIA GPU with ≥6 GB, otherwise `small`.
- GPU→CPU fallback both at model load and mid-inference. On fallback, an auto-picked large model becomes `small`.
- Optional NVIDIA DLL registration for pip-installed cuBLAS/cuDNN (`scripts\enable-gpu.bat`).

**NOT verified:** no real speech has ever been transcribed by this build (huggingface.co is blocked here). Accuracy, Hinglish handling, timestamp precision and speed on Akshar's PC are all unknown.

## Phases 3–5 — Moments, ranking, boundaries: IMPLEMENTED — needs real-video judgment

**Changes since the last update:**
- Everything now runs on **sentence units** (`units.py`) built from word timestamps, split at punctuation, danda and pauses, instead of raw Whisper segments (which can be 30s long).
- Keyword matching is whole-word (no more "ace" in "place") and runs on a Roman transliteration, so Devanagari "भाई" matches "bhai".
- `fit_window` grows each clip from a tight core around the peak toward the preset's preferred length:
  - about 40% setup before the peak;
  - it won't cross a >4s silence unless the clip would otherwise be under the minimum;
  - it trims setup first when too long.
- Cuts are word-accurate: 0.12s before the first word and up to 0.45s after the last, never overlapping neighbouring speech.
- A 1–99 "virality" score (a monotonic mapping of the weighted score) and titles: a heuristic hook sentence, or Ollama when reachable.
- When there aren't enough strong moments, backup picks are added **clearly labelled** ("Backup pick" badge + message) instead of returning 0 clips. This can be turned off.

**Verified:** unit tests for units, fitting, padding, whole-word lexicon, and select/dedup/diversity. The e2e test confirms the loud reaction section lands inside the top clip.

**Still unvalidated:** the weights, thresholds and lexicon against real creator videos.

## Phase 6 — Captions: IMPLEMENTED — renders inspected, needs real-speech judgment

**Implemented:**
- ASS subtitles burned in with libass, six styles: bold_pop, karaoke, clean, boxed, horror, neon.
- Active-word highlight with a pop animation, and hype-word colouring. The emphasis list is deliberately short so everyday words like "bhai" aren't coloured.
- Position, size, words per line, colours, UPPERCASE.
- Line breaks at sentence ends and pauses, with a word budget and a width budget derived from the font. Over-long lines are scaled down, never clipped.
- Bundled OFL fonts. Mukta covers Latin and Devanagari, and any line containing Devanagari switches to a Devanagari-capable font automatically.
- Optional Devanagari→Roman Hinglish transliteration (`translit.py`: common-word dictionary plus schwa deletion; never translation).
- SRT for every clip, and caption text editable per clip.
- The fonts directory is referenced by a relative path inside the data folder, so Windows paths with drive colons or apostrophes can't break the ffmpeg filter (a review finding).

**Verified visually:** contact sheets of every style over time, with Latin and Devanagari text. The review fixed:
- tiny text;
- a shrink/pop scale bug;
- neon glow swallowing the text;
- seams in the boxed style.

**Unverified:** readability on real footage, and timing against real Whisper word timestamps.

## Phase 7 — Reframing: IMPLEMENTED

**Implemented:**
- YuNet face detector (bundled ONNX, MIT) sampled at 2 fps through ffmpeg.
- **Auto** mode:
  - a consistent small face off-centre → facecam **split** (facecam panel sized to its aspect, gameplay cropped below, captions on the seam);
  - a large face → **track** (dead-zone + eased crop path via sendcmd, 10 updates/s);
  - no face → **fit_blur** (full frame over a blurred copy, captions just below the video band).
- Also crop (with a horizontal focus slider) and letterbox; output 9:16, 1:1, 4:5 or 16:9.
- A manual facecam rectangle picker in the editor.

**Verified:** split and fit_blur inspected on a synthetic gameplay video with a real face photo as the facecam. Track produces a monotonic path in unit tests.

**Unverified:** detection robustness on real webcams (lighting, small or partly covered faces), and the tracking feel on real talking-head footage.

## Phase 8 — Presets: IMPLEMENTED

Built-in presets for the target content (Horror Shorts, Gaming Highlights, Funny Moments, Podcast/Talking, Hinglish Reaction) plus the creator's own saved presets (`presets.py`, `/api/presets`; stored in SQLite, never carrying a source range or a per-video facecam area). Home also remembers the last-used settings. Every project stores its own settings; every clip can override captions/framing.

Also added: an optional **hook title** overlay (the clip's title in a white box at the top, for the first 3s/5s or the whole clip; kept small at the very top in the facecam split so it doesn't cover the face). Verified visually.

## Phase 9 — Rendering: IMPLEMENTED

**Implemented:**
- One ffmpeg pass per clip: accurate seek → reframe → captions.
- H.264 high profile, CRF by quality (18/20/23), `+faststart`.
- Audio: AAC 160k, loudnorm to -14 LUFS, 40–80 ms fades so cuts don't click.
- NVENC is tried first when present and it falls back to x264. Output 1080p or 720p.
- Thumbnail extraction.
- Uses the system FFmpeg if it supports libass, otherwise the bundled imageio-ffmpeg 7.1 build (which has libass). Both were verified in Linux; the Windows binary's configuration includes libass.

**Verified:** real renders with correct duration, resolution, codec and audio.

**Unverified:** the NVENC path, and render speed on Akshar's PC.

## Phase 10 — Automated QC: IMPLEMENTED

After each render it checks:
- length vs expected;
- resolution;
- that an audio track exists and isn't near-silent;
- that the clip isn't mostly black frames.

Warnings are shown on the clip card; the clip is still delivered, and the creator decides.

## Phase 11 — Creator review: IMPLEMENTED

**Clip editor:**
- source player with a trim timeline (drag handles, nudges, set-to-playhead, play selection);
- rendered preview;
- title;
- caption style and a live CSS preview using the same fonts;
- caption word editing;
- framing, including the facecam picker.

Edits mark the render as stale, and **Save & render** queues a re-render. Extending a clip whose captions were edited fills the new stretch with transcript words (review fix).

**Around the editor:**
- Manual clips from the Source tab.
- Delete.
- Render all / render changed.
- Zip download of every clip plus SRTs.
- Transcript editing, which marks affected renders stale.

## Infrastructure added this round

**Background jobs** (`jobs.py`):
- SQLite-backed, with a main worker plus a render worker, progress, cancel, and resume-friendly cached steps.
- After a restart, interrupted jobs are failed with a clear message, and their clip and project badges are reset (review fix).
- A cancelled queued render resets its badge.
- A render for a clip deleted mid-queue ends as cancelled, not failed.

**Robustness** (from an independent review pass; each item has a regression test where feasible):
- ffmpeg stderr is always drained, so damaged files can't deadlock the pipe (Windows pipes are only 4 KB).
- `JobCancelled` is a `BaseException`, so a cancel during a YouTube download isn't reported as a network error.
- Deletes wait for running jobs, and folders Windows kept locked are finished at the next start.
- Unique zip files per download.
- A no-audio video gets a specific message and still allows manual clips.
- The launcher only uses Python 3.10–3.12 and removes a half-built environment after a failed first install.

**Single-process production:**
- The backend serves the built UI from `backend/app/static`.
- `ClipForge.bat` handles setup and start, and `run.py` picks a free port and opens the browser.
- Users never need Node.js.

## Known limitations / next tasks

1. **Akshar's real-world run** (checklist above). This is the gate for calling Phases 1–7 done.
2. Keyword/lexicon and weight tuning from real results (Phase 14 benchmarking).
3. Face tracking uses one face (the largest). There is no multi-speaker switching yet.
4. No emoji/sticker overlays, B-roll or auto-zoom effects (OpusClip has these; they're lower priority than clip and caption quality per `CLAUDE.md`).
5. DaVinci Resolve export (XML/EDL) — Phase 13.
