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
}: {
  project: Project;
  settings: ProjectSettings;
  busy: boolean;
  onReprocess: (range: { range_start: number | null; range_end: number | null }) => void;
  onClipAdded: () => void;
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

  const rangeIsWhole = rs <= 0.5 && re >= duration - 0.5;
  const savedStart = settings.range_start ?? 0;
  const savedEnd = settings.range_end ?? duration;
  const rangeChanged = Math.abs(rs - savedStart) > 0.5 || Math.abs(re - savedEnd) > 0.5;

  async function addClip() {
    if (inPt === null || outPt === null) return;
    setAdding(true);
    setError(null);
    try {
      await api.createClip(project.id, { start: Math.min(inPt, outPt), end: Math.max(inPt, outPt), title: clipTitle, render: true });
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
            label="Part of the video to find clips in"
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
            Find clips in {rangeIsWhole ? "the whole video" : `${fmtTime(rs)}–${fmtTime(re)}`}
          </Button>
        </Card>

        <Card className="space-y-3 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Cut a clip yourself</div>
          <p className="text-xs text-slate-400">Play the video, then mark where your clip starts and ends.</p>
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
          <Button
            variant="primary"
            size="sm"
            disabled={inPt === null || outPt === null || Math.abs(outPt - inPt) < 1 || adding}
            onClick={addClip}
          >
            {adding ? "Adding..." : inPt !== null && outPt !== null ? `Add ${Math.abs(outPt - inPt).toFixed(1)}s clip` : "Add clip"}
          </Button>
          {error && <ErrorBox message={error} onDismiss={() => setError(null)} />}
        </Card>
      </div>
    </div>
  );
}
