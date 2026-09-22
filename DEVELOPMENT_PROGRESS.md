# ClipForge — Development Progress

Read this before starting any work. Update it after every meaningful milestone, not just at phase boundaries. See `CLAUDE.md` for the working agreement and `docs/PRODUCT_BRIEF.md` for the full original spec.

Last updated: 2026-09-22

## Phase status

| Phase | Status |
|---|---|
| 0 — Foundation | **COMPLETE** |
| 1 — Video ingestion | **COMPLETE** (local upload verified end-to-end; YouTube implemented but network-blocked in this build environment, see below) |
| 2 — Local transcription | **IMPLEMENTED, orchestration verified — ASR quality NOT verified** (see below, important) |
| 3 — Intelligent moment detection | **IMPLEMENTED, detection logic verified on real signals — needs real video judgment** |
| 4 — Clip ranking | **IMPLEMENTED, scoring/selection logic verified on crafted signals — weights unvalidated against real content** (see below) |
| 5 — Boundary optimization | **IMPLEMENTED, refinement logic verified on crafted signals — needs real video judgment** (see below) |
| 6 — Hinglish captions | NOT STARTED |
| 7 — Smart video editing/reframing | NOT STARTED |
| 8 — Presets | NOT STARTED |
| 9 — Rendering | NOT STARTED |
| 10 — Automated QC | NOT STARTED |
| 11 — Creator review | NOT STARTED |
| 12 — Personalization | NOT STARTED |
| 13 — DaVinci workflow | NOT STARTED |
| 14 — Quality benchmarking | NOT STARTED (ongoing once clips exist) |

**Read this before trusting "COMPLETE" above:** per the phase discipline in `CLAUDE.md`, a phase isn't complete because the code runs — it's complete when the output has been inspected and is meaningfully good. Phases 2, 3, 4 and 5 are marked with their real caveats below instead of a bare COMPLETE, because this build environment could not fully exercise them against real content. Do not upgrade those to COMPLETE until the items under "needs real-world verification" are actually checked.

---

## Phase 0 — Foundation: COMPLETE

(unchanged from before — see git history / previous version of this file for detail. Backend config/logging/errors/hardware detection/SQLite storage/project CRUD, frontend shell with hardware badge and project list, docs, all verified working.)

---

## Phase 1 — Video ingestion: COMPLETE

### What was implemented
- `app/media.py` — ffprobe metadata extraction (duration, resolution, fps, codecs, audio channels/presence, file size, aspect ratio) and ffmpeg-based audio extraction, both with plain-language error handling (`UnsupportedMediaError`, `ExternalToolMissingError`).
- `app/youtube.py` — YouTube URL validation (pure regex, handles watch/shorts/youtu.be/embed links + extra query params) and yt-dlp-based download, with errors translated to plain language (private/age-restricted/removed videos never leak a raw yt-dlp traceback).
- `app/routers/ingest.py` — `POST /api/projects/{id}/upload` (multipart), `POST /api/projects/{id}/youtube`, `GET /api/projects/{id}/media` (range-request-capable, for the `<video>` preview player).
- DB schema extended with `metadata_json`; `ProjectOut` now carries parsed metadata + `has_transcript`/`has_moments`/`has_clips` flags computed from what's actually on disk (not a brittle status-string).
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
- `app/transcription.py` — `FasterWhisperEngine` wrapping faster-whisper: word-level timestamps, VAD filtering, `task="transcribe"` (never `"translate"` — this is the load-bearing line that keeps Hinglish as Hinglish instead of getting flattened into English), language auto-detected rather than forced. Model size configurable (`config.py: whisper_model_size`, override per-request via `?model_size=`). GPU-memory and GPU-runtime failures (including ones that only surface while iterating decoded segments, not at model construction) are caught and translated into `InsufficientResourcesError` with a plain-language suggestion (smaller model / CPU mode) instead of a raw CUDA error, and the engine automatically retries on CPU rather than crashing — see the `whisper_device` (`auto`/`cuda`/`cpu`) setting and the `_is_gpu_runtime_failure()` heuristic.
- `app/routers/transcription.py` — `POST /api/projects/{id}/transcribe`, `GET /api/projects/{id}/transcript`, `PATCH /api/projects/{id}/transcript/segments/{id}` (manual correction, required by the spec — a user shouldn't have to re-transcribe the whole video to fix one word).
- Frontend: `TranscriptPanel.tsx` — transcribe button, scrollable timestamped segment list, click-to-edit inline correction.
- The engine sits behind a small `Protocol` specifically so orchestration is testable without a downloaded model (see below) — this is a deliberate testability seam, not a shortcut in the production code path.

### What was verified (real, not assumed)
- `pytest tests/test_transcription.py`: passing. This covers: full orchestration (upload → transcribe → transcript.json written → project flips to `has_transcript` → GET returns it → scratch audio file cleaned up afterward) using a dependency-injected fake engine that still runs through **real audio extraction** (asserts the engine receives a real, non-empty extracted WAV file); Hinglish text (`"bhai ye kya ho raha hai"`) is preserved verbatim through the whole pipeline, not translated; manual segment editing persists and sets `edited: true`; missing-source and missing-transcript cases return friendly 400/404s; the GPU-runtime-failure-mid-iteration path falls back to CPU rather than propagating a raw CUDA error.
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
- `app/moments.py` — the actual detector: content-type-aware keyword lexicons (English + Hindi/Hinglish slang + gaming terminology, deliberately not translated) combined with exclamation/caps-word text signals and the audio energy signal; candidates are built as **windows** of transcript segments (peak segment + neighboring context/reaction, not a bare timestamp), duration-bounded (10-90s for now); basic overlap de-duplication. Each `Moment` now carries `start_idx`/`end_idx` (the segment-index span, not just timestamps) so Phase 4/5 can re-open and refine the exact window instead of re-deriving it. LLM enrichment is optional and additive — deterministic signals alone are enough to produce a candidate list, matching the spec's explicit "don't rely solely on an LLM's subjective score" requirement.
- `app/routers/moments.py` — `POST /api/projects/{id}/detect-moments`, `GET /api/projects/{id}/moments`.
- Frontend: `MomentsPanel.tsx` — candidate list with category badges, transcript excerpt, plain-language reason, click-to-seek on the video preview.

### What was verified (real, not assumed)
- `pytest tests/test_audio_analysis.py` + `test_moments.py` + `test_moments_router.py`: passing, and these are genuinely meaningful tests, not smoke tests:
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

## Phase 4 — Clip ranking: IMPLEMENTED, scoring/selection logic verified on crafted signals — weights unvalidated against real content

### What was implemented
- `app/ranking.py` — multi-signal scoring per candidate moment: energy (from Phase 3's energy profile), text (keyword/caps/exclamation signal), a new **hook** sub-score (does the window open on something that will stop a scroll — energy spike or an attention-grabbing opener, penalized if it opens mid-sentence on a dangling conjunction like "and"/"so"/"because"), a new **payoff** sub-score (does it end on a resolution/punchline rather than trailing off), a new **standalone** sub-score (can this be understood without the rest of the video — penalizes windows that open on a bare pronoun/reference with no antecedent in-window), and a **duration_fit** sub-score (how close the refined length lands to the requested preset's preferred duration). Sub-scores are combined via fixed weights (`WEIGHTS` — hook and payoff weighted highest, matching the product brief's "hook in the first 3 seconds, satisfying payoff" priority) into a single `total_score`.
- Selection (`select_clips()`) is a real ranking pass, not a bare top-N: sorts by `total_score`, keeps only clips at/above a `PUBLISHABLE_SCORE_THRESHOLD`, de-duplicates overlapping windows (>40% overlap keeps only the higher-scoring one), and applies a soft per-category diversity cap (max 2 of the same category before backfilling from the next-best of a different category) so the result isn't five near-identical "funny" clips back to back. When fewer clips clear the bar than requested, the result says so honestly via a `message` field rather than padding the list with weak candidates — this was an explicit product-brief requirement ("never pad to hit a number").
- `app/duration_presets.py` — the four named presets from the brief (Ultra Short 10-20s, Short 20-35s, Standard 30-60s, Extended 60-90s) plus a validated `custom` preset with min/max/preferred bounds.
- `app/routers/clips.py` — `POST /api/projects/{id}/generate-clips` (count, duration_preset, optional custom bounds), `GET /api/projects/{id}/clips`, persisting `clips.json` and reflected via a new `has_clips` project flag.
- Frontend: `ClipsPanel.tsx` — duration preset selector, clip-count input, "Generate clips" button, ranked list with category badge, total score, transcript excerpt, plain-language reason, duration explanation, an expandable sub-score breakdown per clip, and click-to-seek on the shared video preview. Wired into `ProjectDetail.tsx` below `MomentsPanel`, gated on `project.has_moments`.

### What was verified (real, not assumed)
- `pytest tests/test_ranking.py`: 8/8 passing — unit tests per sub-score function (hook score responds to a real energy spike at the window start and penalizes a dangling-conjunction opener; payoff score responds to trailing energy/resolution language; standalone score penalizes an unresolved pronoun opener; duration_fit score peaks at the preset's preferred duration and falls off toward the bounds), plus `select_clips()` behavior tests confirming: overlapping candidates are de-duplicated to the higher scorer, the category diversity cap actually kicks in and backfills from a different category, and a request for more clips than clear the publishable threshold returns fewer clips with an honest `message` instead of padding.
- `pytest tests/test_clips_router.py`: 5/5 passing — full API integration via `TestClient` using the same fake-engine dependency-injection pattern as the moments router tests (upload → transcribe → detect-moments → generate-clips → `clips.json` on disk → `has_clips` reflected → `GET /clips` returns the same result), plus bad-preset-value rejection (`ValidationFailedError` → clean 400, not a 500).
- Full backend regression: **53/53 tests passing** after this phase's additions (up from 40 before Phase 4/5), confirming nothing in Phases 0-3 broke.
- Frontend builds clean (`tsc -b && vite build`, zero TypeScript errors) with `ClipsPanel.tsx` and the new `Clip`/`ClipsResult`/`DurationPreset` types wired in.

### What was NOT verified — and this is the important caveat
**The scoring weights (`WEIGHTS` in `ranking.py`) and the publishable-score threshold are reasonable-but-unvalidated heuristics.** They were chosen to match the product brief's stated priorities (hook and payoff matter most) and confirmed to respond correctly to the *specific* crafted signals in the unit tests above — but no one has yet looked at a batch of ranked clips from a real gaming/Hinglish video and confirmed the top-ranked ones are actually the best ones a human would pick. The diversity cap (max 2 per category) and overlap threshold (40%) are also first-pass numbers, not tuned. **This is expected to need real-world calibration** — per `CLAUDE.md`'s own rule that human judgment is the final quality gate, not test coverage.

**Action needed:** once you have real moments detected on your machine, generate clips and tell me: are the top-ranked ones actually the best candidates, does the diversity cap feel right or does it force in a weaker clip too eagerly, does any duration preset feel off.

---

## Phase 5 — Boundary optimization: IMPLEMENTED, refinement logic verified on crafted signals — needs real video judgment

### What was implemented
- `app/boundaries.py` — `refine_boundaries()`, called by `ranking.py: score_and_refine()` for every candidate before scoring, so ranking always operates on the *refined* window, not Phase 3's raw one. Two real behaviors, not placeholders:
  - **Filler trimming**: strips leading filler-only segments (a lexicon of English + Hinglish fillers — "um", "so", "actually", "arey", "acha", "haan", etc. — only trims segments short enough and entirely filler, never eats into real content) so a clip doesn't open on a throat-clear.
  - **Reaction extension**: if the window ends right before a short gap followed by continued loud energy (e.g. a reaction/laugh that trails just past the original window), it extends to include it — but only up to a hard overrun cap (`MAX_DURATION_OVERRUN_RATIO`, 1.15x the preset's max) so it can't runaway-extend a clip past its duration bounds chasing "one more loud segment."
  - Produces a human-readable `duration_explanation` string (e.g. `"Recommended duration: 32 seconds -- trimmed a filler opener, extended slightly to include the reaction."`) surfaced directly in the UI so the duration choice isn't a black box.

### What was verified (real, not assumed)
- `pytest tests/test_boundaries.py`: 5/5 passing, including two real bugs this session's own tests caught and fixed before commit (not shipped-then-found bugs):
  - `test_trims_leading_filler_segment` — caught that an overly-aggressive guard (originally tied to the full preset's minimum duration) was silently preventing filler trimming on short candidate windows; fixed by removing the guard, since the loop's own condition already guarantees at least one segment survives.
  - `test_does_not_extend_past_max_duration_overrun_tolerance` — caught that the overrun check was evaluating the window's duration *before* the prospective extension instead of after, so it always allowed "one more" extension regardless of how far past the cap it would land; fixed to check the duration the extension would actually produce.
  - The other three tests confirm: a window with no filler/no trailing reaction is left unchanged (`explanation` says so plainly), reaction-extension only fires when both the gap is short *and* the trailing energy is still loud (not just any short gap), and the refined `start_idx`/`end_idx` stay consistent with the returned `start`/`end` timestamps.
- Exercised indirectly through every `test_ranking.py` and `test_clips_router.py` test above, since ranking always refines before scoring — the refinement path is on the hot path of every clip that gets generated, not a side branch.

### What was NOT verified — needs real video judgment
**Like Phase 3, this has only been exercised against hand-crafted `SimpleNamespace` segments and synthetic energy arrays, never a real transcript with real filler patterns and real reaction timing.** The filler lexicon is a reasonable first pass (common English fillers + a handful of Hindi/Hinglish ones the brief calls out) but almost certainly incomplete against real speech. The gap/energy thresholds for reaction-extension (`REACTION_EXTEND_GAP_THRESHOLD` = 2.0s, `REACTION_EXTEND_ENERGY_Z` = 1.0σ) are unvalidated guesses.

**Action needed:** same as Phase 4 — once real clips are generated from a real video, check whether the `duration_explanation` text matches what actually happened (did it really trim a filler, does the extension feel natural or does it cut off a reaction too early/late).

---

## Cross-phase: live end-to-end smoke test (earlier session)

Ran the actual `uvicorn` server (not TestClient) and drove it with `curl` through a real pipeline: create project → upload a real ffmpeg-generated video → correct metadata came back over HTTP → media streamed back successfully → transcribe attempted with the real engine → failed exactly as designed with a clean `503` and a plain-language message (`"Couldn't load the local transcription model... Check your connection and try again."`), no raw error leaking through, confirmed both in the HTTP response and that the technical detail (`403 Forbidden`) only appears in the server-side log, not the client response.

## Known bugs / issues
None currently open. (Two bugs were found and fixed during Phase 4/5 development itself — see the Phase 5 section above — but neither shipped to `main` in a broken state; they were caught by this session's own tests before commit.)

## Next tasks
1. **You**: run this on your machine, try a real YouTube URL, try a real Hindi/Hinglish gaming clip through transcription + moment detection + clip generation, tell me what's actually wrong with the output. This is the single highest-value thing that can happen next — everything past Phase 1 is implemented against my best judgment but unverified against real content.
2. Phase 6 — Hinglish captions: burned-in caption generation and styling, keeping Hinglish code-switching intact (same "never translate" principle as Phase 2).
3. Phase 7 — Smart reframing/editing: vertical (9:16) reframe with speaker/action-aware cropping, not a naive center-crop.
4. Consider background-job execution for transcribe/detect-moments/generate-clips (currently synchronous, blocking the HTTP request) once real video lengths make that painful — noted here rather than silently deferred.
