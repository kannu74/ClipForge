import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { Moment, Project } from "../lib/types";

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

function fmtTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function MomentsPanel({ project, videoRef }: Props) {
  const [moments, setMoments] = useState<Moment[] | null>(null);
  const [ollamaUsed, setOllamaUsed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (project.has_moments) {
      api.getMoments(project.id).then((r) => {
        setMoments(r.moments);
        setOllamaUsed(r.ollama_used);
      });
    }
  }, [project.id, project.has_moments]);

  async function handleDetect() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.detectMoments(project.id);
      setMoments(r.moments);
      setOllamaUsed(r.ollama_used);
    } catch (err) {
      setError(
        err instanceof ApiError ? (err.suggestion ? `${err.message} ${err.suggestion}` : err.message) : "Moment detection failed."
      );
    } finally {
      setBusy(false);
    }
  }

  if (!project.has_transcript) {
    return (
      <div className="rounded-2xl border border-surface-border bg-surface-raised p-6 text-sm text-slate-500">
        Transcribe the video first -- moment detection reads the transcript.
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-surface-border bg-surface-raised p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">Candidate moments</h2>
          {moments && (
            <p className="mt-0.5 text-xs text-slate-500">
              {moments.length} candidate{moments.length === 1 ? "" : "s"} ·{" "}
              {ollamaUsed ? "LLM-enriched" : "deterministic signals only (Ollama not reachable)"}
            </p>
          )}
        </div>
        {!project.has_moments && (
          <button
            onClick={handleDetect}
            disabled={busy}
            className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          >
            {busy ? "Analyzing..." : "Detect moments"}
          </button>
        )}
      </div>

      {error && (
        <p className="mt-3 rounded-lg border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">{error}</p>
      )}

      {moments && moments.length === 0 && (
        <p className="mt-3 text-sm text-slate-500">
          No strong candidates found. This detector is still an early, deterministic-signal-only
          version -- ranking and diversity come in Phase 4.
        </p>
      )}

      {moments && moments.length > 0 && (
        <div className="mt-4 space-y-2">
          {moments.map((m) => (
            <button
              key={m.id}
              onClick={() => {
                if (videoRef.current) {
                  videoRef.current.currentTime = m.start;
                  videoRef.current.play();
                }
              }}
              className="block w-full rounded-xl border border-surface-border p-3 text-left hover:border-accent/60"
            >
              <div className="flex items-center justify-between">
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${CATEGORY_COLORS[m.category] ?? "bg-slate-500/20 text-slate-300"}`}>
                  {m.category}
                </span>
                <span className="font-mono text-[11px] text-slate-500">
                  {fmtTime(m.start)} - {fmtTime(m.end)} ({(m.end - m.start).toFixed(0)}s)
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-300">"{m.transcript_excerpt}"</p>
              <p className="mt-1 text-xs text-slate-500">{m.reason}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
