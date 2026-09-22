import { useEffect, useMemo, useRef, useState } from "react";
import { api, errorText } from "../lib/api";
import { fmtTime } from "../lib/format";
import type { CaptionSettings, CaptionWord, Clip, Project, ProjectSettings, ReframeSettings } from "../lib/types";
import CaptionPreview from "./CaptionPreview";
import FacecamPicker from "./FacecamPicker";
import { CaptionControls, FramingControls } from "./SettingsControls";
import TrimTimeline from "./TrimTimeline";
import { Button, ErrorBox, Modal, Segmented } from "./ui";

function same(a: unknown, b: unknown) {
  return JSON.stringify(a) === JSON.stringify(b);
}

export default function ClipEditor({
  project,
  settings,
  clip,
  onClose,
  onSaved,
}: {
  project: Project;
  settings: ProjectSettings;
  clip: Clip;
  onClose: () => void;
  onSaved: () => void;
}) {
  const duration = project.metadata?.duration_seconds ?? clip.end + 30;
  const [start, setStart] = useState(clip.start);
  const [end, setEnd] = useState(clip.end);
  const [title, setTitle] = useState(clip.title);
  const [cap, setCap] = useState<CaptionSettings>({ ...settings.captions, ...(clip.caption_overrides ?? {}) } as CaptionSettings);
  const [ref, setRef] = useState<ReframeSettings>({ ...settings.reframe, ...(clip.reframe_overrides ?? {}) } as ReframeSettings);
  const [words, setWords] = useState<CaptionWord[] | null>(null);
  const [wordsEdited, setWordsEdited] = useState(false);
  const [wordsDirty, setWordsDirty] = useState(false);
  const [tab, setTab] = useState<"trim" | "captions" | "text" | "framing">("trim");
  const [view, setView] = useState<"source" | "rendered">(clip.render.status === "done" ? "rendered" : "source");
  const [current, setCurrent] = useState(clip.start);
  const [loopPlay, setLoopPlay] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pickFacecam, setPickFacecam] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    api
      .getWords(project.id, clip.id)
      .then((r) => {
        setWords(r.words);
        setWordsEdited(r.edited);
      })
      .catch(() => setWords([]));
  }, [project.id, clip.id]);

  useEffect(() => {
    const v = videoRef.current;
    if (v && view === "source") v.currentTime = start;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  const rangeChanged = Math.abs(start - clip.start) > 0.01 || Math.abs(end - clip.end) > 0.01;
  const capChanged = !same(cap, { ...settings.captions, ...(clip.caption_overrides ?? {}) });
  const refChanged = !same(ref, { ...settings.reframe, ...(clip.reframe_overrides ?? {}) });
  const dirty = rangeChanged || capChanged || refChanged || wordsDirty || title !== clip.title;

  const visibleWords = useMemo(
    () => (words ?? []).filter((w) => (w.start + w.end) / 2 >= start - 0.05 && (w.start + w.end) / 2 <= end + 0.05),
    [words, start, end]
  );
  const sampleText = visibleWords.slice(0, 12).map((w) => w.word).join(" ") || "bhai WAIT no way";

  function seek(t: number) {
    const v = videoRef.current;
    if (v) v.currentTime = t;
    setCurrent(t);
  }

  function playClip() {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = start;
    setLoopPlay(true);
    v.play();
  }

  async function save(render: boolean) {
    setSaving(true);
    setError(null);
    try {
      // 1. Range first, so the server can fill caption words for any newly
      //    included stretch before we apply the creator's word edits.
      if (rangeChanged) {
        await api.patchClip(project.id, clip.id, { start, end });
      }
      // 2. Word edits, re-applied on top of the (possibly extended) word list.
      if (wordsDirty && words) {
        const edits = new Map(words.map((w) => [w.start.toFixed(2), w.word]));
        const fresh = rangeChanged ? (await api.getWords(project.id, clip.id)).words : words;
        const merged = fresh.map((w) => ({ ...w, word: edits.get(w.start.toFixed(2)) ?? w.word }));
        await api.putWords(project.id, clip.id, merged);
      }
      // 3. Everything else (+ render).
      const capOverride = same(cap, settings.captions) ? null : cap;
      const refOverride = same(ref, settings.reframe) ? null : ref;
      await api.patchClip(project.id, clip.id, {
        title: title !== clip.title ? title : undefined,
        ...(capChanged
          ? capOverride
            ? { caption_overrides: capOverride as unknown as Record<string, unknown> }
            : { clear_caption_overrides: true }
          : {}),
        ...(refChanged
          ? refOverride
            ? { reframe_overrides: refOverride as unknown as Record<string, unknown> }
            : { clear_reframe_overrides: true }
          : {}),
        render,
      });
      onSaved();
      onClose();
    } catch (e) {
      setError(errorText(e, "Couldn't save the clip."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open onClose={onClose} title={`Edit clip — ${clip.title || "Untitled"}`} wide>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_420px]">
        {/* Left: player */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <Segmented
              size="sm"
              value={view}
              onChange={setView}
              options={[
                { value: "source", label: "Source video" },
                { value: "rendered", label: clip.render.status === "done" ? "Rendered clip" : "Rendered (not yet)" },
              ]}
            />
            {view === "source" && (
              <div className="flex gap-1.5">
                <Button size="sm" onClick={playClip}>
                  ▶ Play clip
                </Button>
              </div>
            )}
          </div>
          {view === "source" ? (
            <video
              ref={videoRef}
              src={api.mediaUrl(project.id)}
              className="aspect-video w-full rounded-xl bg-black"
              controls
              preload="metadata"
              onTimeUpdate={(e) => {
                const t = e.currentTarget.currentTime;
                setCurrent(t);
                if (loopPlay && t >= end) {
                  e.currentTarget.pause();
                  e.currentTarget.currentTime = start;
                  setLoopPlay(false);
                }
              }}
              onLoadedMetadata={(e) => (e.currentTarget.currentTime = start)}
            />
          ) : clip.render.status === "done" ? (
            <div className="flex justify-center rounded-xl bg-black">
              <video
                src={api.clipVideoUrl(project.id, clip.id, clip.render.rendered_at)}
                controls
                autoPlay
                className="max-h-[520px] rounded-xl"
              />
            </div>
          ) : (
            <div className="flex aspect-video items-center justify-center rounded-xl bg-surface text-sm text-slate-500">
              This clip hasn't been rendered yet — use “Save & render”.
            </div>
          )}
          {view === "source" && (
            <>
              <TrimTimeline
                duration={duration}
                start={start}
                end={end}
                current={current}
                onChange={(s, e) => {
                  setStart(s);
                  setEnd(e);
                }}
                onSeek={seek}
              />
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="text-slate-500">Start</span>
                <Button size="sm" onClick={() => setStart((s) => Math.max(0, s - 1))}>−1s</Button>
                <Button size="sm" onClick={() => setStart((s) => Math.max(0, s - 0.2))}>−0.2</Button>
                <Button size="sm" onClick={() => setStart((s) => Math.min(end - 1, s + 0.2))}>+0.2</Button>
                <Button size="sm" onClick={() => setStart((s) => Math.min(end - 1, s + 1))}>+1s</Button>
                <Button size="sm" onClick={() => setStart(Math.min(current, end - 1))}>Set to playhead</Button>
                <span className="ml-3 text-slate-500">End</span>
                <Button size="sm" onClick={() => setEnd((e) => Math.max(start + 1, e - 1))}>−1s</Button>
                <Button size="sm" onClick={() => setEnd((e) => Math.max(start + 1, e - 0.2))}>−0.2</Button>
                <Button size="sm" onClick={() => setEnd((e) => Math.min(duration, e + 0.2))}>+0.2</Button>
                <Button size="sm" onClick={() => setEnd((e) => Math.min(duration, e + 1))}>+1s</Button>
                <Button size="sm" onClick={() => setEnd(Math.max(current, start + 1))}>Set to playhead</Button>
              </div>
              {rangeChanged && (
                <button
                  className="text-xs text-slate-500 underline hover:text-slate-300"
                  onClick={() => {
                    setStart(clip.start);
                    setEnd(clip.end);
                  }}
                >
                  Undo trim ({fmtTime(clip.start, true)} → {fmtTime(clip.end, true)})
                </button>
              )}
            </>
          )}
        </div>

        {/* Right: controls */}
        <div className="space-y-4">
          <Segmented
            size="sm"
            value={tab}
            onChange={setTab}
            options={[
              { value: "trim", label: "Title" },
              { value: "captions", label: "Caption style" },
              { value: "text", label: "Caption text" },
              { value: "framing", label: "Framing" },
            ]}
          />
          <div className="max-h-[560px] overflow-y-auto pr-1">
            {tab === "trim" && (
              <div className="space-y-4">
                <label className="block space-y-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Title</span>
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-slate-100 outline-none focus:border-accent"
                  />
                  <span className="text-xs text-slate-500">
                    Used as the download file name{cap.title_overlay ? " and shown at the top of the video" : ""}.
                  </span>
                </label>
                <div className="rounded-lg bg-surface p-3 text-xs text-slate-400">
                  <p>{clip.reason}</p>
                  <p className="mt-1">{clip.duration_explanation}</p>
                </div>
                <div className="flex justify-center">
                  <CaptionPreview
                    cfg={cap}
                    sample={sampleText}
                    height={320}
                    background={api.frameUrl(project.id, start + 0.5, 480)}
                    title={cap.title_overlay ? title : undefined}
                  />
                </div>
                {!cap.title_overlay && (
                  <button className="text-xs text-accent underline" onClick={() => setCap((c) => ({ ...c, title_overlay: true }))}>
                    Show this title at the top of the video
                  </button>
                )}
              </div>
            )}
            {tab === "captions" && (
              <div className="space-y-4">
                <CaptionControls value={cap} onChange={(p) => setCap((c) => ({ ...c, ...p }))} showPreview={false} narrow />
                <div className="flex justify-center">
                  <CaptionPreview
                    cfg={cap}
                    sample={sampleText}
                    height={320}
                    background={api.frameUrl(project.id, start + 0.5, 480)}
                    title={cap.title_overlay ? title : undefined}
                  />
                </div>
                {capChanged && (
                  <button className="text-xs text-slate-500 underline" onClick={() => setCap(settings.captions)}>
                    Reset to the project's caption style
                  </button>
                )}
              </div>
            )}
            {tab === "text" && (
              <div className="space-y-3">
                <p className="text-xs text-slate-400">
                  Fix any word the transcription got wrong. Timing stays the same. Changes only affect this clip's captions.
                </p>
                {words === null ? (
                  <div className="text-sm text-slate-500">Loading words...</div>
                ) : visibleWords.length === 0 ? (
                  <div className="text-sm text-slate-500">No speech in this part of the video.</div>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {visibleWords.map((w) => {
                      const idx = words.indexOf(w);
                      return (
                        <input
                          key={`${idx}-${w.start}`}
                          value={w.word}
                          onFocus={() => seek(w.start)}
                          onChange={(e) => {
                            const next = [...words];
                            next[idx] = { ...w, word: e.target.value };
                            setWords(next);
                            setWordsDirty(true);
                          }}
                          title={`${fmtTime(w.start, true)}`}
                          style={{ width: `calc(${Math.max(2, w.word.length)}ch + 1.6rem)` }}
                          className="rounded-md border border-surface-border bg-surface px-1.5 py-1 text-sm text-slate-100 outline-none focus:border-accent"
                        />
                      );
                    })}
                  </div>
                )}
                <p className="text-xs text-slate-500">
                  Clear a word's box to remove it from the captions.
                  {rangeChanged && " Words for a newly added part of the clip appear after you save."}
                </p>
                {(wordsEdited || wordsDirty) && (
                  <button
                    className="text-xs text-slate-500 underline"
                    onClick={async () => {
                      const r = await api.putWords(project.id, clip.id, null);
                      setWords(r.words);
                      setWordsEdited(false);
                      setWordsDirty(false);
                    }}
                  >
                    Reset caption text to the transcript
                  </button>
                )}
              </div>
            )}
            {tab === "framing" && (
              <div className="space-y-3">
                <FramingControls value={ref} onChange={(p) => setRef((r) => ({ ...r, ...p }))} onPickFacecam={() => setPickFacecam(true)} narrow />
                {clip.render.reframe_note && (
                  <p className="rounded-lg bg-surface p-2 text-xs text-slate-400">Last render: {clip.render.reframe_note}</p>
                )}
                {refChanged && (
                  <button className="text-xs text-slate-500 underline" onClick={() => setRef(settings.reframe)}>
                    Reset to the project's framing
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {error && (
        <div className="mt-4">
          <ErrorBox message={error} onDismiss={() => setError(null)} />
        </div>
      )}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-surface-border pt-4">
        <span className="mr-auto text-xs text-slate-500">{dirty ? "Unsaved changes" : "No changes"}</span>
        <Button onClick={onClose}>Close</Button>
        <Button disabled={!dirty || saving} onClick={() => save(false)}>
          Save
        </Button>
        <Button variant="primary" disabled={saving} onClick={() => save(true)}>
          {saving ? "Saving..." : dirty ? "Save & render" : "Re-render"}
        </Button>
      </div>

      {pickFacecam && (
        <FacecamPicker
          open
          onClose={() => setPickFacecam(false)}
          projectId={project.id}
          time={start + 1}
          duration={duration}
          initial={ref.facecam ?? clip.render.facecam_detected ?? null}
          onSave={(rect) => setRef((r) => ({ ...r, facecam: rect, mode: r.mode === "auto" ? "split" : r.mode }))}
        />
      )}
    </Modal>
  );
}
