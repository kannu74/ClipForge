import { useRef, useState } from "react";
import { api, errorText } from "../lib/api";
import { fmtBytes, fmtTime } from "../lib/format";
import type { Project, ProjectSettings } from "../lib/types";
import TrimTimeline from "./TrimTimeline";
import { Button, Card, ErrorBox, Field } from "./ui";

/** Source video: choose which part to process, and cut clips by hand. */
export default function SourceTab({
  project,
  settings,
  busy,
  onReprocess,
  onClipAdded,
  captionOnly = false,
}: {
  project: Project;
  settings: ProjectSettings;
  busy: boolean;
  onReprocess: (range: { range_start: number | null; range_end: number | null }) => void;
  onClipAdded: () => void;
  captionOnly?: boolean;
}) {
  const duration = project.metadata?.duration_seconds ?? 0;
  const videoRef = useRef<HTMLVideoElement>(null);
  const [current, setCurrent] = useState(0);
  const [rs, setRs] = useState(settings.range_start ?? 0);
  const [re, setRe] = useState(settings.range_end ?? duration);
  const [inPt, setInPt] = useState<number | null>(null);
  const [outPt, setOutPt] = useState<number | null>(null);
  const [clipTitle, setClipTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  // Hand-marked clips waiting to be created together: Clip 1, Clip 2, ...
  const [queue, setQueue] = useState<{ start: number; end: number; title: string }[]>([]);

  const rangeIsWhole = rs <= 0.5 && re >= duration - 0.5;
  const savedStart = settings.range_start ?? 0;
  const savedEnd = settings.range_end ?? duration;
  const rangeChanged = Math.abs(rs - savedStart) > 0.5 || Math.abs(re - savedEnd) > 0.5;

  function queueClip() {
    if (inPt === null || outPt === null) return;
    const n = queue.length + 1;
    setQueue([...queue, { start: Math.min(inPt, outPt), end: Math.max(inPt, outPt), title: clipTitle.trim() || `Clip ${n}` }]);
    setInPt(null);
    setOutPt(null);
    setClipTitle("");
  }

  async function addClip() {
    // A marked-but-unqueued range counts too, so "Add" never silently drops it.
    const pending =
      inPt !== null && outPt !== null && Math.abs(outPt - inPt) >= 1
        ? [{ start: Math.min(inPt, outPt), end: Math.max(inPt, outPt), title: clipTitle.trim() || `Clip ${queue.length + 1}` }]
        : [];
    const all = [...queue, ...pending];
    if (all.length === 0) return;
    setAdding(true);
    setError(null);
    try {
      await api.createClipsBatch(project.id, { clips: all, render: true });
      setQueue([]);
      setInPt(null);
      setOutPt(null);
      setClipTitle("");
      onClipAdded();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setAdding(false);
    }
  }

  if (!project.metadata) return null;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-3">
        <video
          ref={videoRef}
          src={api.mediaUrl(project.id)}
          controls
          preload="metadata"
          className="aspect-video w-full rounded-xl bg-black"
          onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
        />
        <div className="text-xs text-slate-500">
          {project.metadata.width}×{project.metadata.height} · {project.metadata.fps} fps · {fmtTime(duration)} ·{" "}
          {fmtBytes(project.metadata.file_size_bytes)} · {project.source_type === "youtube" ? `YouTube: ${project.source_reference}` : project.source_reference}
        </div>
      </div>
      <div className="space-y-5">
        <Card className="space-y-3 p-4">
          <Field
            label={captionOnly ? "Part of the video to caption" : "Part of the video to find clips in"}
            hint="Great for long streams: skip the intro/outro or focus on one section. Changing it re-transcribes that part."
          >
            <TrimTimeline
              duration={duration}
              start={rs}
              end={re}
              current={current}
              context={duration}
              onChange={(s, e) => {
                setRs(Math.max(0, s));
                setRe(Math.min(duration, e));
              }}
              onSeek={(t) => {
                if (videoRef.current) videoRef.current.currentTime = t;
              }}
            />
            <div className="flex flex-wrap gap-1.5">
              <Button size="sm" onClick={() => setRs(Math.min(current, re - 10))}>
                Start at playhead
              </Button>
              <Button size="sm" onClick={() => setRe(Math.max(current, rs + 10))}>
                End at playhead
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setRs(0);
                  setRe(duration);
                }}
              >
                Whole video
              </Button>
            </div>
          </Field>
          <Button
            variant="primary"
            disabled={busy || !rangeChanged}
            onClick={() =>
              onReprocess({
                range_start: rangeIsWhole || rs <= 0.5 ? null : Math.round(rs * 10) / 10,
                range_end: rangeIsWhole || re >= duration - 0.5 ? null : Math.round(re * 10) / 10,
              })
            }
          >
            {captionOnly ? "Caption" : "Find clips in"} {rangeIsWhole ? "the whole video" : `${fmtTime(rs)}–${fmtTime(re)}`}
          </Button>
        </Card>

        {!captionOnly && <Card className="space-y-3 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{captionOnly ? "Caption range" : "Cut a clip yourself"}</div>
          <p className="text-xs text-slate-400">{captionOnly ? "Choose the portion to caption. The output keeps the source framing." : "Play the video, mark where a clip starts and ends, save it as Clip 1, then do Clip 2, 3… Create them all at once — they render with your current caption and framing settings."}</p>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={() => setInPt(current)}>
              Mark start {inPt !== null && `(${fmtTime(inPt)})`}
            </Button>
            <Button size="sm" onClick={() => setOutPt(current)}>
              Mark end {outPt !== null && `(${fmtTime(outPt)})`}
            </Button>
          </div>
          <input
            value={clipTitle}
            onChange={(e) => setClipTitle(e.target.value)}
            placeholder="Title (optional)"
            className="w-full rounded-lg border border-surface-border bg-surface px-3 py-1.5 text-sm text-slate-100 outline-none focus:border-accent"
          />
          {!captionOnly && <Button
            size="sm"
            disabled={inPt === null || outPt === null || Math.abs(outPt - inPt) < 1}
            onClick={queueClip}
          >
            {inPt !== null && outPt !== null ? `Save as Clip ${queue.length + 1} (${Math.abs(outPt - inPt).toFixed(1)}s)` : "Save as next clip"}
          </Button>}
          {!captionOnly && queue.length > 0 && (
            <ul className="space-y-1 text-xs text-slate-300">
              {queue.map((q, i) => (
                <li key={i} className="flex items-center justify-between gap-2 rounded-lg bg-surface px-2 py-1">
                  <span className="truncate">
                    {q.title} · {fmtTime(q.start)}–{fmtTime(q.end)}
                  </span>
                  <button className="text-slate-500 hover:text-red-400" onClick={() => setQueue(queue.filter((_, k) => k !== i))}>
                    remove
                  </button>
                </li>
              ))}
            </ul>
          )}
          {!captionOnly && <Button
            variant="primary"
            size="sm"
            disabled={adding || (queue.length === 0 && (inPt === null || outPt === null || Math.abs(outPt - inPt) < 1))}
            onClick={addClip}
          >
            {adding
              ? "Adding..."
              : `Create & render ${queue.length + (inPt !== null && outPt !== null && Math.abs(outPt - inPt) >= 1 ? 1 : 0) || ""} clip${
                  queue.length + (inPt !== null && outPt !== null ? 1 : 0) === 1 ? "" : "s"
                } with the current preset`}
          </Button>}
          {error && <ErrorBox message={error} onDismiss={() => setError(null)} />}
        </Card>}
      </div>
    </div>
  );
}
