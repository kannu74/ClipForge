import { useState } from "react";
import { api } from "../lib/api";
import { cx, fmtBytes, fmtDuration, viralityColor } from "../lib/format";
import type { Clip, Job } from "../lib/types";
import { Button, LinkButton, ProgressBar, Spinner } from "./ui";

const CATEGORY_LABEL: Record<string, string> = {
  funny: "😂 Funny",
  scare: "😱 Scare",
  rage: "😤 Rage",
  clutch: "🔥 Clutch",
  fail: "💀 Fail",
  surprise: "😮 Surprise",
  reaction: "🎭 Reaction",
  story: "📖 Story",
  manual: "✂️ Manual",
};

export default function ClipCard({
  projectId,
  clip,
  index,
  job,
  onEdit,
  onRender,
  onDelete,
  captionsOn = true,
}: {
  captionsOn?: boolean;
  projectId: string;
  clip: Clip;
  index: number;
  job?: Job;
  onEdit: () => void;
  onRender: () => void;
  onDelete: () => void;
}) {
  const r = clip.render;
  const [showWhy, setShowWhy] = useState(false);
  const version = r.rendered_at ?? "";
  const duration = clip.end - clip.start;
  // Trust the live job list: a "queued"/"rendering" badge without a live job
  // means the render was interrupted, so offer to render again.
  const rendering = job?.status === "running" || job?.status === "queued";
  const aspectClass =
    r.width && r.height ? (r.width > r.height ? "aspect-video" : r.width === r.height ? "aspect-square" : "aspect-[9/16]") : "aspect-[9/16]";

  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-surface-border bg-surface-raised">
      <div className={cx("relative w-full bg-black", aspectClass)}>
        {r.status === "done" && !rendering && r.file ? (
          <video
            key={version}
            src={api.clipVideoUrl(projectId, clip.id, version)}
            poster={r.thumbnail ? api.clipThumbUrl(projectId, clip.id, version) : undefined}
            controls
            preload="none"
            playsInline
            className="h-full w-full object-contain"
          />
        ) : (
          <div className="relative h-full w-full">
            <img
              src={api.frameUrl(projectId, clip.start + Math.min(1, duration / 3), 480)}
              alt=""
              className="h-full w-full object-cover opacity-40"
              loading="lazy"
            />
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-4 text-center">
              {rendering ? (
                <>
                  <Spinner className="h-6 w-6 text-white" />
                  <div className="text-xs text-slate-200">
                    {job?.status === "running" ? job.message ?? "Rendering..." : "Waiting to render..."}
                  </div>
                  {job?.status === "running" && <ProgressBar value={job.progress} className="w-3/4" />}
                </>
              ) : r.status === "failed" ? (
                <>
                  <div className="text-sm text-red-300">Render failed</div>
                  <div className="text-xs text-slate-300">{r.error}</div>
                  <Button size="sm" variant="primary" onClick={onRender}>
                    Try again
                  </Button>
                </>
              ) : (
                <Button size="sm" variant="primary" onClick={onRender}>
                  Render video
                </Button>
              )}
            </div>
          </div>
        )}
        <div className="pointer-events-none absolute left-2 top-2 flex gap-1.5">
          <span className="rounded-md bg-black/70 px-1.5 py-0.5 font-mono text-[11px] text-slate-200">#{index + 1}</span>
          {clip.origin === "auto" && (
            <span className={cx("rounded-md border px-1.5 py-0.5 text-[11px] font-semibold backdrop-blur", viralityColor(clip.virality))}>
              {clip.virality}/99
            </span>
          )}
        </div>
        {clip.confidence === "low" && (
          <span className="pointer-events-none absolute right-2 top-2 rounded-md bg-amber-500/90 px-1.5 py-0.5 text-[11px] font-semibold text-black">
            Backup pick
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="line-clamp-2 text-sm font-semibold text-slate-100" title={clip.title}>
          {clip.title || "Untitled clip"}
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
          <span className="rounded-full bg-surface px-2 py-0.5">{CATEGORY_LABEL[clip.category] ?? clip.category}</span>
          <span>{fmtDuration(duration)}</span>
          {r.size_bytes ? <span>· {fmtBytes(r.size_bytes)}</span> : null}
          {clip.edited && <span className="text-accent">· edited</span>}
          <span
            className={cx(
              "rounded px-1.5 py-0.5 font-mono text-[10px]",
              captionsOn ? "bg-accent/20 text-accent" : "bg-slate-700 text-slate-400 line-through"
            )}
            title={captionsOn ? "Captions are burned in" : "No captions"}
          >
            CC
          </span>
        </div>
        {r.status === "done" && r.stale && !rendering && (
          <div className="rounded-lg border border-amber-800 bg-amber-950/40 px-2 py-1 text-xs text-amber-300">
            Changed since last render.{" "}
            <button onClick={onRender} className="font-semibold underline">
              Re-render
            </button>
          </div>
        )}
        {r.qc && !r.qc.passed && (
          <div className="rounded-lg border border-amber-800 bg-amber-950/30 px-2 py-1 text-xs text-amber-300">
            {r.qc.warnings.join(" ")}
          </div>
        )}
        <button onClick={() => setShowWhy((v) => !v)} className="text-left text-xs text-slate-500 hover:text-slate-300">
          {showWhy ? "▾" : "▸"} Why this clip
        </button>
        {showWhy && (
          <div className="space-y-1 rounded-lg bg-surface p-2 text-xs text-slate-400">
            <p>{clip.reason}</p>
            <p>{clip.duration_explanation}</p>
            {r.reframe_note && <p>Framing: {r.reframe_note}</p>}
            <p className="italic text-slate-500">“{clip.transcript_excerpt.slice(0, 220)}{clip.transcript_excerpt.length > 220 ? "…" : ""}”</p>
          </div>
        )}
        <div className="mt-auto flex flex-wrap gap-1.5 pt-1">
          <Button size="sm" variant="primary" onClick={onEdit}>
            ✎ Edit
          </Button>
          {r.status === "done" && (
            <>
              <LinkButton size="sm" href={api.clipDownloadUrl(projectId, clip.id)} download>
                ⬇ MP4
              </LinkButton>
              <LinkButton size="sm" href={api.clipSrtUrl(projectId, clip.id)} download title="Caption file">
                SRT
              </LinkButton>
            </>
          )}
          <Button size="sm" variant="ghost" onClick={onDelete} title="Delete clip">
            🗑
          </Button>
        </div>
      </div>
    </div>
  );
}
