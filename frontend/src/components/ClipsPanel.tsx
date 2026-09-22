import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { DURATION_PRESET_LABELS, type Clip, type DurationPreset, type Project } from "../lib/types";

interface Props {
  project: Project;
  videoRef: React.RefObject<HTMLVideoElement>;
}

const CATEGORY_COLORS: Record<string, string> = {
  funny: "bg-yellow-500/20 text-yellow-300",
  scare: "bg-purple-500/20 text-purple-300",
  rage: "bg-red-500/20 text-red-300",
  clutch: "bg-emerald-500/20 text-emerald-300",
  fail: "bg-orange-500/20 text-orange-300",
  surprise: "bg-sky-500/20 text-sky-300",
  reaction: "bg-pink-500/20 text-pink-300",
  story: "bg-slate-500/20 text-slate-300",
};

const PRESET_OPTIONS: DurationPreset[] = ["ultra_short", "short", "standard", "extended"];

function fmtTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function fmtScore(n: number): string {
  return n.toFixed(2);
}

export default function ClipsPanel({ project, videoRef }: Props) {
  const [clips, setClips] = useState<Clip[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [preset, setPreset] = useState<DurationPreset>("standard");
  const [count, setCount] = useState(5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (project.has_clips) {
      api.getClips(project.id).then((r) => {
        setClips(r.clips);
        setMessage(r.message);
        setPreset((r.duration_preset as DurationPreset) ?? "standard");
        setCount(r.requested_count);
      });
    }
  }, [project.id, project.has_clips]);

  async function handleGenerate() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.generateClips(project.id, count, preset);
      setClips(r.clips);
      setMessage(r.message);
    } catch (err) {
      setError(
        err instanceof ApiError ? (err.suggestion ? `${err.message} ${err.suggestion}` : err.message) : "Clip generation failed."
      );
    } finally {
      setBusy(false);
    }
  }

  if (!project.has_moments) {
    return (
      <div className="rounded-2xl border border-surface-border bg-surface-raised p-6 text-sm text-slate-500">
        Detect moments first -- clip ranking reads the candidate moments.
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-surface-border bg-surface-raised p-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">Ranked clips</h2>
          {clips && (
            <p className="mt-0.5 text-xs text-slate-500">
              {clips.length} clip{clips.length === 1 ? "" : "s"} selected
            </p>
          )}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-slate-500">
          Duration
          <select
            value={preset}
            onChange={(e) => setPreset(e.target.value as DurationPreset)}
            disabled={busy}
            className="rounded-lg border border-surface-border bg-surface px-2 py-1.5 text-xs text-slate-200"
          >
            {PRESET_OPTIONS.map((p) => (
              <option key={p} value={p}>
                {DURATION_PRESET_LABELS[p]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-500">
          Count
          <input
            type="number"
            min={1}
            max={50}
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.min(50, Number(e.target.value) || 1)))}
            disabled={busy}
            className="w-16 rounded-lg border border-surface-border bg-surface px-2 py-1.5 text-xs text-slate-200"
          />
        </label>
        <button
          onClick={handleGenerate}
          disabled={busy}
          className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover disabled:opacity-50"
        >
          {busy ? "Ranking..." : clips ? "Regenerate clips" : "Generate clips"}
        </button>
      </div>

      {error && (
        <p className="mt-3 rounded-lg border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">{error}</p>
      )}

      {message && (
        <p className="mt-3 rounded-lg border border-amber-900 bg-amber-950/30 px-3 py-2 text-xs text-amber-300">{message}</p>
      )}

      {clips && clips.length === 0 && !message && (
        <p className="mt-3 text-sm text-slate-500">No clips cleared the publishable-quality bar.</p>
      )}

      {clips && clips.length > 0 && (
        <div className="mt-4 space-y-2">
          {clips.map((c) => (
            <div key={c.id} className="rounded-xl border border-surface-border p-3 hover:border-accent/60">
              <button
                onClick={() => {
                  if (videoRef.current) {
                    videoRef.current.currentTime = c.start;
                    videoRef.current.play();
                  }
                }}
                className="block w-full text-left"
              >
                <div className="flex items-center justify-between">
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${CATEGORY_COLORS[c.category] ?? "bg-slate-500/20 text-slate-300"}`}>
                    {c.category}
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="font-mono text-[11px] text-slate-500">
                      {fmtTime(c.start)} - {fmtTime(c.end)} ({(c.end - c.start).toFixed(0)}s)
                    </span>
                    <span className="rounded-full bg-accent/20 px-2 py-0.5 font-mono text-[11px] text-accent">
                      {fmtScore(c.total_score)}
                    </span>
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-300">"{c.transcript_excerpt}"</p>
                <p className="mt-1 text-xs text-slate-500">{c.reason}</p>
                <p className="mt-1 text-xs text-slate-600">{c.duration_explanation}</p>
                {!c.llm_enriched && (
                  <p className="mt-1 text-[10px] uppercase tracking-wide text-slate-600">deterministic signals only</p>
                )}
              </button>
              <button
                onClick={() => setExpanded(expanded === c.id ? null : c.id)}
                className="mt-2 text-[11px] text-slate-500 hover:text-slate-300"
              >
                {expanded === c.id ? "Hide sub-scores" : "Show sub-scores"}
              </button>
              {expanded === c.id && (
                <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-slate-400 sm:grid-cols-6">
                  {Object.entries(c.sub_scores).map(([k, v]) => (
                    <div key={k} className="rounded-lg bg-surface px-2 py-1 text-center">
                      <div className="text-slate-500">{k}</div>
                      <div className="font-mono text-slate-300">{fmtScore(v)}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
