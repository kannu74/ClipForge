# ClipForge — Development Progress

Read this before starting any work. Update it after every meaningful milestone, not just at phase boundaries. See `CLAUDE.md` for the working agreement and `docs/PRODUCT_BRIEF.md` for the full original spec.

Last updated: 2026-09-17

## Phase status

| Phase | Status |
|---|---|
| 0 — Foundation | **COMPLETE** |
| 1 — Video ingestion | **COMPLETE** (local upload verified end-to-end; YouTube implemented but network-blocked in this build environment, see below) |
| 2 — Local transcription | **IMPLEMENTED, orchestration verified — ASR quality NOT verified** (see below, important) |
| 3 — Intelligent moment detection | **IMPLEMENTED, detection logic verified on real signals — needs real video judgment** |
| 4 — Clip ranking | NOT STARTED |
| 5 — Boundary optimization | NOT STARTED (basic windowing exists inside Phase 3, not the full pass) |
| 6 — Hinglish captions | NOT STARTED |
| 7 — Smart video editing/reframing | NOT STARTED |
| 8 — Presets | NOT STARTED |
| 9 — Rendering | NOT STARTED |
| 10 — Automated QC | NOT STARTED |
| 11 — Creator review | NOT STARTED |
| 12 — Personalization | NOT STARTED |
| 13 — DaVinci workflow | NOT STARTED |
| 14 — Quality benchmarking | NOT STARTED (ongoing once clips exist) |

**Read this before trusting "COMPLETE" above:** per the phase discipline in `CLAUDE.md`, a phase isn't complete because the code runs — it's complete when the output has been inspected and is meaningfully good. Phases 2 and 3 are marked with their real caveats below instead of a bare COMPLETE, because this build environment could not fully exercise them. Do not upgrade those to COMPLETE until the items under "needs real-world verification" are actually checked.

---

## Phase 0 — Foundation: COMPLETE

(unchanged from before — see git history / previous version of this file for detail. Backend config/logging/errors/hardware detection/SQLite storage/project CRUD, frontend shell with hardware badge and project list, docs, all verified working.)

---

## Phase 1 — Video ingestion: COMPLETE

### What was implemented
- `app/media.py` — ffprobe metadata extraction (duration, resolution, fps, codecs, audio channels/presence, file size, aspect ratio) and ffmpeg-based audio extraction, both with plain-language error handling (`UnsupportedMediaError`, `ExternalToolMissingError`).
- `app/youtube.py` — YouTube URL validation (pure regex, handles watch/shorts/youtu.be/embed links + extra query params) and yt-dlp-based download, with errors translated to plain language (private/age-restricted/removed videos never leak a raw yt-dlp traceback).
- `app/routers/ingest.py` — `POST /api/projects/{id}/upload` (multipart), `POST /api/projects/{id}/youtube`, `GET /api/projects/{id}/media` (range-request-capable, for the `<video>` preview player).
- DB schema extended with `metadata_json`; `ProjectOut` now carries parsed metadata + `has_transcript`/`has_moments` flags computed from what's actually on disk (not a brittle status-string).
- Frontend: `SourcePanel.tsx` — drag/click file upload or YouTube URL input, then a real `<video>` preview with metadata line (duration/resolution/fps/codecs/size/source type).

### What was verified (real, not assumed)
- `pytest tests/test_ingest.py`: 15/15 passing, including **against a real ffmpeg-generated MP4** (640x360, h264/aac) — not a mock. Confirms ffprobe extraction returns correct duration/resolution/fps/codecs/aspect ratio, upload end-to-end (file lands on disk, project status flips to `ready`, media is retrievable), bad-extension rejection, and pure-logic YouTube URL validation against 4 valid and 4 invalid URL shapes.
- **Live server smoke test** (not TestClient — an actual running `uvicorn` process hit with `curl`): created a project, uploaded a real generated video, got back correct metadata over HTTP, and successfully streamed it back from `/media` (200 OK).
- Frontend builds clean (`tsc -b && vite build`, zero errors) with the new upload/YouTube/preview UI wired in.

### What was NOT verified — network-blocked in this build environment
Both this device sandbox and the cloud build container have `youtube.com` blocked at the network proxy level (`403 from proxy` on connect). **The YouTube download path (`app/youtube.py: download()`, the `/api/projects/{id}/youtube` endpoint) is implemented correctly but has never actually downloaded a real video in this environment.** What *is* verified: URL validation (real, no network needed) and that a bad URL is rejected before the project gets stuck in `ingesting`. What's NOT verified: that yt-dlp's actual download/merge/rename flow works end to end on Akshar's machine. **Action needed: try a real YouTube URL once ClipForge is running on your machine and tell me if it breaks.**

---

## Phase 2 — Local transcription: IMPLEMENTED, orchestration verified — ASR quality NOT verified

### What was implemented
- `app/transcription.py` — `FasterWhisperEngine` wrapping faster-whisper: word-level timestamps, VAD filtering, `task="transcribe"` (never `"translate"` — this is the load-bearing line that keeps Hinglish as Hinglish instead of getting flattened into English), language auto-detected rather than forced. Model size configurable (`config.py: whisper_model_size`, override per-request via `?model_size=`). GPU-memory failures are caught and translated into `InsufficientResourcesError` with a plain-language suggestion (smaller model / CPU mode) instead of a raw CUDA error.
- `app/routers/transcription.py` — `POST /api/projects/{id}/transcribe`, `GET /api/projects/{id}/transcript`, `PATCH /api/projects/{id}/transcript/segments/{id}` (manual correction, required by the spec — a user shouldn't have to re-transcribe the whole video to fix one word).
- Frontend: `TranscriptPanel.tsx` — transcribe button, scrollable timestamped segment list, click-to-edit inline correction.
- The engine sits behind a small `Protocol` specifically so orchestration is testable without a downloaded model (see below) — this is a deliberate testability seam, not a shortcut in the production code path.

### What was verified (real, not assumed)
- `pytest tests/test_transcription.py`: 5/5 passing. This covers: full orchestration (upload → transcribe → transcript.json written → project flips to `has_transcript` → GET returns it → scratch audio file cleaned up afterward) using a dependency-injected fake engine that still runs through **real audio extraction** (asserts the engine receives a real, non-empty extracted WAV file); Hinglish text (`"bhai ye kya ho raha hai"`) is preserved verbatim through the whole pipeline, not translated; manual segment editing persists and sets `edited: true`; missing-source and missing-transcript cases return friendly 400/404s.
- **The important one**: `test_real_engine_fails_gracefully_without_model_access` calls the **real** `FasterWhisperEngine` (no mocking) against a real video, with no network access to huggingface.co. It confirms the failure is caught and returned as a clean 503 with a plain-language message — not a 500, not a raw traceback, no "CUDA"/"traceback" leaking into the response. Confirmed on a live running server too (see the curl smoke test at the end of this doc).

### What was NOT verified — this is the important caveat for this phase
**No actual speech-to-text inference has been run anywhere in this build process.** Both the local device sandbox and the cloud build container have `huggingface.co` blocked at the network proxy (`403 from proxy`), which is faster-whisper's model source — so a `WhisperModel(...)` can never actually be instantiated here, real or fake video. This means:
- Transcription **accuracy** — including the entire point of Phase 2, Hinglish quality — has not been observed even once.
- Word-timestamp precision hasn't been checked against real speech.
- No model size (tiny/base/small/medium/large-v3) has been compared for quality vs. speed on this machine.
- The spec's own gate for this phase ("do not move on until transcription quality is acceptable") **cannot be honestly claimed as met.** What's actually true: the code is real (not a stub), the plumbing around it is proven correct, and it fails safely when it can't reach the network it needs.

**Action needed:** run ClipForge for real on your machine (which should have normal internet access, unlike this sandbox), transcribe a real Hindi/Hinglish gaming clip, and tell me what's wrong with it. Given CPU-only or modest-GPU hardware, expect `small` or `medium` to be the realistic floor for decent Hinglish code-switching — `tiny`/`base` are fast but noticeably worse at it; this needs your real judgment, not mine, per the product brief's own "human evaluation is the final authority" rule.

---

## Phase 3 — Intelligent moment detection: IMPLEMENTED, detection logic verified — needs real video judgment

### What was implemented
- `app/audio_analysis.py` — deterministic short-time RMS loudness analysis (ffmpeg decode → numpy), independent of any model or network.
- `app/llm.py` — `OllamaClient`, configurable host/model, every call wrapped so an unreachable/misconfigured Ollama degrades to "no enrichment" rather than breaking detection.
- `app/moments.py` — the actual detector: content-type-aware keyword lexicons (English + Hindi/Hinglish slang + gaming terminology, deliberately not translated) combined with exclamation/caps-word text signals and the audio energy signal; candidates are built as **windows** of transcript segments (peak segment + neighboring context/reaction, not a bare timestamp), duration-bounded (10-90s for now); basic overlap de-duplication. LLM enrichment is optional and additive — deterministic signals alone are enough to produce a candidate list, matching the spec's explicit "don't rely solely on an LLM's subjective score" requirement.
- `app/routers/moments.py` — `POST /api/projects/{id}/detect-moments`, `GET /api/projects/{id}/moments`.
- Frontend: `MomentsPanel.tsx` — candidate list with category badges, transcript excerpt, plain-language reason, click-to-seek on the video preview.

### What was verified (real, not assumed)
- `pytest tests/test_audio_analysis.py` + `test_moments.py` + `test_moments_router.py`: 9/9 passing, and these are genuinely meaningful tests, not smoke tests:
  - `test_energy_profile_distinguishes_loud_from_quiet` — real ffmpeg-synthesized audio (quiet/loud/quiet), confirms the energy analyzer actually reads a >1σ spike in the loud section and near-zero in the quiet sections.
  - `test_detect_moments_finds_the_exciting_window` — combines that real energy profile with a hand-crafted transcript where the exciting line ("WAIT WHAT?! NO WAY! ARE YOU SERIOUS?!") lines up with the loud window; asserts the detector actually picks it as the top candidate, with the correct category, a non-empty explanation, and a window that includes surrounding context (not just the peak line alone).
  - `test_detect_moments_respects_content_type_lexicon` — confirms horror-relevant Hinglish ("bhai this game is so scary, I think there's a bhoot in here") gets categorized as `scare`, proving content-type-aware evaluation actually works, not just generic energy detection.
  - `test_ollama_enrichment_path_via_injected_client` — proves the LLM-enrichment merge logic (category override, score adjustment, reason replacement) works correctly via a fake client, since real Ollama isn't reachable here.
  - `test_detect_moments_end_to_end` — full API-level run: upload → transcribe → detect-moments → moments.json on disk → `has_moments` reflected on the project.
- Confirmed **on the live running server** (not just TestClient) that `ollama_reachable: false` in this sandbox correctly falls through to deterministic-only detection without crashing.

### What was NOT verified — and this is the big one
**No real gaming/creator video has gone through this detector.** Everything above is real, working logic verified against genuinely crafted signals (real audio spikes, real Hinglish text) — but that is categorically not the same as "finds genuinely interesting moments in an actual messy gaming video with background game audio, multiple speakers, and real timing," which is what Phase 3's actual definition of done requires. The keyword lexicons are a reasonable first pass but are hand-guessed, not tuned against real creator speech patterns. Ollama enrichment has never run against a real local model. **This phase cannot be called "meaningfully better" yet — only "correctly implemented and internally consistent."**

**Action needed:** once you have a real gaming/Hinglish clip transcribed (see Phase 2's action item), run moment detection on it and tell me honestly: did it find the actual good moments, did it miss anything obvious, did the boundaries feel right, is the category label sensible? That feedback is what turns this from "implemented" into "good."

---

## Cross-phase: live end-to-end smoke test (this session)

Ran the actual `uvicorn` server (not TestClient) and drove it with `curl` through a real pipeline: create project → upload a real ffmpeg-generated video → correct metadata came back over HTTP → media streamed back successfully → transcribe attempted with the real engine → failed exactly as designed with a clean `503` and a plain-language message (`"Couldn't load the local transcription model... Check your connection and try again."`), no raw error leaking through, confirmed both in the HTTP response and that the technical detail (`403 Forbidden`) only appears in the server-side log, not the client response.

## Known bugs / issues
None currently open.

## Next tasks
1. **You**: run this on your machine, try a real YouTube URL, try a real Hindi/Hinglish gaming clip through transcription + moment detection, tell me what's actually wrong with the output. This is the single highest-value thing that can happen next — everything past this point is implemented against my best judgment but unverified against real content.
2. Phase 4 — Clip ranking: multi-signal scoring (hook/payoff/emotion/humor/surprise/standalone comprehension/etc.), real diversity enforcement (Phase 3's de-dup is a placeholder), explanation generation.
3. Phase 5 — Boundary optimization: Phase 3's window-building is intentionally basic; this needs sentence-boundary-aware refinement, "don't start mid-sentence," configurable duration presets (Ultra Short/Short/Standard/Extended) actually wired to user choice.
4. Consider background-job execution for transcribe/detect-moments (currently synchronous, blocking the HTTP request) once real video lengths make that painful — noted here rather than silently deferred.
