import type { Job } from "../lib/types";
import { cx } from "../lib/format";
import { Button, Card, ProgressBar, Spinner } from "./ui";

const STEPS: { key: string; label: string }[] = [
  { key: "download", label: "Download" },
  { key: "transcribe", label: "Transcribe" },
  { key: "analyze", label: "Find moments" },
  { key: "rank", label: "Pick & trim clips" },
  { key: "render", label: "Render videos" },
];

export default function PipelineProgress({
  job,
  renderJobs,
  onCancel,
}: {
  job: Job | null;
  renderJobs: Job[];
  onCancel?: () => void;
}) {
  const activeRenders = renderJobs.filter((j) => j.status === "queued" || j.status === "running");
  const isRenderOnly = !job && activeRenders.length > 0;
  const rawStage = job ? job.stage ?? (job.status === "queued" ? "queued" : "download") : "render";
  // "preview" (browser preview copy) and "done" happen after clips are picked.
  const stage = rawStage === "preview" || rawStage === "done" ? "render" : rawStage;
  const steps = job && !job.params?.youtube_url ? STEPS.filter((s) => s.key !== "download") : STEPS;
  const currentIdx = Math.max(0, steps.findIndex((s) => s.key === stage));
  const renderDone = renderJobs.filter((j) => j.status === "done").length;
  const renderTotal = renderJobs.length;
  const renderFrac = renderTotal
    ? (renderDone + activeRenders.reduce((a, j) => a + (j.status === "running" ? j.progress : 0), 0)) / renderTotal
    : 0;
  const progress = isRenderOnly ? renderFrac : job?.progress ?? 0;
  const message = isRenderOnly
    ? `Rendering clips: ${renderDone} of ${renderTotal} done`
    : job?.status === "queued"
      ? "Waiting for the previous task to finish..."
      : job?.message ?? "Working...";

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Spinner className="h-5 w-5 text-accent" />
          <div>
            <div className="text-sm font-semibold text-slate-100">{isRenderOnly ? "Rendering your clips" : "Working on your video"}</div>
            <div className="text-xs text-slate-400">{message}</div>
          </div>
        </div>
        {onCancel && job && (
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
      <ProgressBar value={progress} className="mt-4" />
      <div className="mt-4 flex flex-wrap gap-2">
        {steps.map((s, i) => {
          const done = isRenderOnly ? s.key !== "render" : i < currentIdx;
          const active = isRenderOnly ? s.key === "render" : i === currentIdx;
          return (
            <div
              key={s.key}
              className={cx(
                "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs",
                done && "border-emerald-800 bg-emerald-950/40 text-emerald-300",
                active && "border-accent bg-accent/15 text-white",
                !done && !active && "border-surface-border text-slate-500"
              )}
            >
              {done ? "✓" : active ? "●" : "○"} {s.label}
            </div>
          );
        })}
      </div>
      {stage === "transcribe" && !isRenderOnly && (
        <p className="mt-3 text-xs text-slate-500">
          Transcription is the slow part — roughly real-time on a laptop CPU, much faster on an NVIDIA GPU. The first run also
          downloads the speech model once. You can leave this page; it keeps running.
        </p>
      )}
    </Card>
  );
}
