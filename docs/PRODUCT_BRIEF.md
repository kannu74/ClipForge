# ClipForge — Full Product Brief (original, verbatim from product owner)

This is the complete, unabridged brief given by Akshar (product owner) at project kickoff (2026-09-17). `CLAUDE.md` is the condensed working agreement derived from this; when the two seem to conflict, this file is the source of truth for intent, `CLAUDE.md` is the source of truth for day-to-day conventions.

## 1. Product vision

Build a local-first AI clipping platform inspired by products such as OpusClip, but specifically optimized for: gaming content, gaming commentary, funny gaming moments, horror games, reactions, comedy, streamer content, YouTube creators, Hindi content, Hinglish content, English content, YouTube long-form videos converted into Shorts/Reels/TikToks, and long-form videos converted into shorter landscape clips.

The product should allow a user to provide either a locally stored video or a YouTube video URL. The system should analyze the content and automatically identify the strongest moments, generate clips, caption them, reframe them for vertical platforms, and allow the creator to review and customize everything before export. It should feel like a serious creator tool, not an experimental AI demo.

## 2. Core user workflow

Create project -> upload local video or YouTube URL -> select content type -> choose preset -> choose duration -> choose clip count -> analyze -> find moments -> rank moments -> determine boundaries -> create clips -> generate captions -> reframe -> optional effects -> QC -> review -> edit/reject/regenerate -> customize captions/duration/preset -> export -> optionally continue in DaVinci Resolve.

## 3. Local-first requirement

Must run fully on the user's machine without a cloud AI subscription. Local AI is the default. Ollama is the supported local LLM runtime; the model must be user-selectable/configurable, never hard-coded. Use local models where practical for transcription, content understanding, clip identification/ranking, caption processing, visual understanding. No video/audio/content sent externally by default; any optional external service must be clearly separated from the local workflow. Must work offline after models/deps are downloaded, except when the user provides a YouTube URL.

## 4. Hardware awareness

Detect CPU, RAM, GPU, VRAM, CUDA availability. Offer quality/performance modes: Fast, Balanced, High Quality, Maximum Quality. Never assume a high-end GPU; gracefully fall back to CPU. Never crash because a model doesn't fit in VRAM. Long videos must be processed without unnecessary memory consumption.

## 5. Input video support

MP4, MOV, MKV, WebM, AVI (where supported). Extract duration, resolution, FPS, video/audio codec, audio tracks, file size, aspect ratio. Show processing info. Give meaningful errors on unsupported input.

## 6. YouTube input

Validate URL, retrieve the permitted video, get metadata, then process locally. Respect access restrictions/copyright; never attempt to bypass private videos, DRM, paywalls. Remainder of pipeline runs local once source is downloaded.

## 7. Project management

A project preserves: source info, original video, processing status, transcript, detected moments, generated clip candidates, selected clips, caption data, preset settings, user edits, QC results, exported clips, user ratings/feedback. Reopening a project must not re-process the source from scratch. Cache intermediate analysis. A failure halfway through should be resumable, not a forced full restart.

## 8. Content types

At minimum: Gaming, Funny gaming, Horror gaming, Reaction, Comedy, Commentary, Storytelling, General creator content. Content type changes how moments are evaluated (e.g. horror -> suspense/setup/scare/scream/reaction/aftermath; comedy -> setup/timing/buildup/pause/punchline/reaction; gaming -> clutch/fail/rage/unexpected event/funny interaction/achievement/surprise/reaction). Never treat every video as generic talking-head content.

## 9-10. Intelligent moment discovery (the most important feature)

Must identify genuinely interesting moments, not just high-energy sections. Categories: funny, unexpected, scares, screams, rage, clutches, fails, victories, losses, surprises, reactions, arguments, interesting statements, story moments, emotional moments, memorable interactions, gameplay highlights, unexpected dialogue, strong jokes/punchlines, interesting explanations. Must understand context: a scream alone is weaker than setup -> suspense -> event -> scream -> reaction; a punchline alone is weaker than setup -> buildup -> pause -> punchline -> reaction. Identify the complete moment, not just the loudest timestamp.

## 11. Clip quality principle

Every clip should be evaluated against: HOOK + CONTEXT + EVENT + PAYOFF + CLEAN ENDING. Not every clip needs all five, but all five should be considered. A clip should make sense to someone who never watched the source. Include only as much context as needed — not more "to be safe."

## 12. Clip boundaries

Never assume the interesting timestamp is the correct clip start. Examine nearby timestamps to choose the best start/end. Beginning should feel natural — avoid starting mid-sentence, right after setup, after the joke has already begun, or without needed context. Ending should include punchline/reaction/resolution/natural stopping point — avoid cutting right after the event, before the reaction, mid-sentence, or abruptly. For every promising moment, consider multiple candidate boundaries and pick the most coherent.

## 13. Clip duration

Configurable. Presets: Ultra Short 10-20s, Short 20-35s, Standard 30-60s, Extended 60-90s, plus custom min/max/preferred. Never cut for hitting a duration target if it destroys semantic completeness (e.g. don't trim the last 5s of a 63s clip if that's the payoff). The system should be able to explain its duration choice ("Recommended duration: 63 seconds because the reaction completes the moment.").

## 14. Clip count

User picks 1/3/5/10/custom. Never pad to the requested count with mediocre clips — if only 6 genuinely strong candidates exist, say so. Quality over quota.

## 15. Clip ranking

Evaluate multiple signals: hook strength, payoff strength, emotional intensity, humor, surprise, novelty, standalone comprehension, context requirement, story completeness, visual quality, audio quality, caption confidence, platform suitability, rewatch potential, beginning quality, ending quality. Don't rely solely on an LLM's subjective score — use deterministic signals too. Explain why a clip was selected.

## 16. Clip diversity

Don't return near-duplicate clips from the same short section. Prefer a diverse set (e.g. one scare, one funny fail, one rage moment, one clutch, one unexpected interaction) over five clips from the same 90 seconds. Avoid excessive temporal overlap unless moments are genuinely distinct.

## 17. Hinglish is first-class

Speech mixes Hindi + English + gaming terminology + slang + abbreviations + internet language. Preserve natural Hinglish rather than translating it. E.g. "shit ye kya ho raha hai" must stay as-is, not become "shit what is happening."

## 18. Transcription quality

Preserve natural speech, slang, Hindi/English words, gaming terms, names, abbreviations. No hallucinated words. Word-level timestamps wherever possible. Captions must stay synced to actual speech. User must be able to manually correct transcription.

## 19-22. Caption system

Dynamic short-form captions with intelligent line breaks (avoid awkward breaks unless the style calls for it) and natural timing. Full customization: font, size, weight, color, highlight color, stroke/width, shadow, background/opacity, position, alignment, vertical position, max words/chars per line, case, letter/line spacing, animation style, word highlighting, emphasis. Multiple caption presets. Animation styles: static, word-by-word, pop, bounce, scale, fade, highlight, karaoke, emphasis — configurable, not over-animated on every word; emphasis should be used intelligently (e.g. "WHAT THE HELL?!" hits harder than "so then I went over there"). A caption editor must allow editing text/timing/splitting/merging/emphasis/style/position with live preview, without regenerating the whole clip for one word.

## 23-24. Smart reframing & gaming-specific editing

Support 16:9, 9:16 (primary), 1:1. For vertical, intelligently decide what stays visible (faces, speakers, gameplay action, important objects, enemies, characters, UI, visual events) — never blind center crop, never jittery movement, crop should move smoothly, never accidentally remove important gameplay info. Gaming content may optionally get punch-ins, dynamic zoom, reaction emphasis, important-event focus, subtle camera movement, smart cropping — only when it serves the content, never gratuitously.

## 25-26. Silence removal & optional effects

Remove dead air but never blindly remove every silence — some silence is load-bearing for comedy timing, suspense, horror, emotional beats, dramatic buildup; distinguish meaningful pauses from useless dead air (critical for comedy/horror). Optional effects (SFX, zooms, transitions, emphasis, motion, background treatment) defined per-preset, tasteful by default, never overpowering the content.

## 27-28. Presets

Built-in presets: Gaming Shorts, Funny Gaming, Horror Gaming, Clean Creator, Story Clip, Landscape (see brief for exact per-preset settings). Users can create/name/edit/duplicate/delete custom presets and persist caption style, duration prefs, aspect ratio, editing behavior, AI selection prefs — a creator's own signature style.

## 29-31. Batch processing, long videos, preview

Show current task/progress/phase/errors/retry options; failed operations recoverable. Must handle 30min-3+hr videos without loading the whole file into memory; cache intermediates. Fast preview of original/vertical crop/captions/effects/timing without a full high-quality render each iteration.

## 32. Quality control (mandatory, automated)

Technical: corrupted/black/frozen frames, missing audio, audio clipping, invalid duration/FPS/resolution, encoding failures. Caption: text outside safe area, overlap, bad line breaks, incorrect timing, missing/repeated words, suspicious transcription, unreadable captions. Editing: abrupt start/end, bad crop, jitter, excessive zoom, missing reaction/punchline, excessive dead air. Semantic: too much required context, weak hook, no payoff, not interesting enough, duplicate content, incomplete joke/reaction. A clip isn't "finished" until it passes QC.

## 33-34. Human review & creator quality loop

Every clip: accept/reject/edit/regenerate/rate (1-5 stars), with reasons (bad hook, bad timing, too much context, not funny, weak moment, bad captions, bad crop, bad ending, good clip). Feedback stored. Loop: generate -> review -> rate -> learn preferences -> generate better clips. Build this foundation honestly (explicit preferences + stored feedback) — don't pretend it's ML if it's a static preference system yet.

## 35-36. Export & DaVinci Resolve workflow

Export for YouTube Shorts/Reels/TikTok/YouTube/general MP4, configurable resolution/FPS/quality/bitrate/audio, sensible defaults. DaVinci continuation: preserve original source timestamps, clip boundaries, caption info, editing info; eventually support EDL/XML/FCPXML export. Not a prerequisite for the core product.

## 37-39. UI requirements

Modern professional creator app: clean, dark mode, fast workflow, clear progress, large previews, easy clip comparison, minimal required config with advanced options tucked away. Main flow: Upload -> Content type -> Preset -> Duration -> Clip count -> Generate -> Review -> Edit -> Export. Each generated clip shows preview, duration, type, source timestamp, quality info, why-selected explanation, caption preview, edit/reject/regenerate/export actions, easy comparison. For long videos, navigable moment list by category (funny/scary/rage/clutch/fail/reaction/story/surprise) with timestamps and jump-to-source.

## 40-43. Performance, error handling, configuration, privacy

Cache aggressively — never re-transcribe an unchanged video, never re-analyze an unchanged segment, never regenerate unchanged captions, avoid full re-render when only a small part changed. Errors must be understandable and actionable, never raw technical errors like "CUDA error: invalid argument" (translate to plain language + a recovery suggestion). Users configure AI model, quality mode, GPU/CPU preference, processing quality, clip count/duration/aspect ratio, caption/editing preset, export quality — without editing source code. Media stays local by default; no unnecessary personal data collection; don't expose local files unnecessarily.

## 44. Development philosophy

Real product, not a demo. No fake functionality to make the UI look complete, no dead buttons, no placeholder AI results once a phase is being implemented. Mark unimplemented things as unimplemented. Prefer a smaller fully-working feature over ten fake ones.

## 45. Phased implementation plan (authoritative phase list)

Phase 0 Foundation, 1 Video ingestion, 2 Local transcription, 3 Intelligent moment detection, 4 Clip ranking, 5 Boundary optimization, 6 Hinglish captions, 7 Smart video editing/reframing, 8 Presets, 9 Rendering, 10 Automated QC, 11 Creator review, 12 Personalization, 13 DaVinci workflow, 14 Quality benchmarking (ongoing). Each phase has a definition of done in the original brief — see chat history / ask Akshar to re-paste if a specific phase's DoD needs to be re-checked; the essential ones are captured per-phase in `DEVELOPMENT_PROGRESS.md` as each phase is opened.

## 46-48. Quality gates, testing, benchmarking

Never declare "phase complete" without: implementation working, tests passing, real inputs tested, outputs actually inspected, known problems documented. For AI clipping specifically, a phase is not done because the model returns timestamps — it's done when resulting clips are meaningfully better. Test with real creator-style videos: long gaming, horror gameplay, fast speech, Hindi/Hinglish speech, heavy slang, loud reactions, multiple speakers, background game audio, quiet conversation, comedy timing. Maintain a benchmark of manually-judged clips; for every major pipeline change compare old vs new on hook/boundary/payoff/captions/framing/duplicates/false-positives. Human evaluation is the final authority, never a model's self-reported score.

## 49-51. Progress tracking & build order

Maintain `DEVELOPMENT_PROGRESS.md` with per-phase status (NOT STARTED / IN PROGRESS / BLOCKED / TESTING / COMPLETE), what was implemented, what works, what was tested + results, known bugs, known quality problems, next tasks. Before major changes: inspect current project, understand existing code, check progress doc, identify what's already implemented, avoid unnecessary rewrites. After changes: run tests, start the app, test the feature, inspect real output, fix errors, update docs and progress. Investigate root causes, not workarounds. Build progressively in this order: ingestion -> transcription -> moment detection -> ranking -> boundary quality -> captions -> editing -> rendering -> QC -> UI polish -> personalization -> advanced integrations. A beautiful UI with poor clips is not success.

## 52-54. Final standard

The only question that matters for a generated clip: "Would I actually publish this?" — not "did the AI identify an event," not "did the code run," not "did the model score it 95." End goal: take a 1-3 hour gaming video and produce a curated set of strong short-form clips with strong hooks, good context, complete moments, strong reactions, good pacing, excellent Hinglish/English captions, intelligent vertical framing, tasteful editing, clean endings, minimal manual work. Priority order when deciding what to work on: clip quality > boundary quality > transcription quality > caption quality > semantic understanding > reframing quality > rendering reliability > QC > creator workflow > performance > UI polish > additional features.

Start by inspecting the repo state, identify the current phase, implement the next incomplete phase incrementally, test with real videos, update `DEVELOPMENT_PROGRESS.md` after every meaningful milestone. Do not skip ahead to advanced features.
