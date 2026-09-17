import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { Project, Transcript } from "../lib/types";

interface Props {
  project: Project;
  onTranscribed: () => void;
}

function fmtTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(1);
  return `${m}:${s.padStart(4, "0")}`;
}

export default function TranscriptPanel({ project, onTranscribed }: Props) {
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    if (project.has_transcript) {
      api.getTranscript(project.id).then(setTranscript).catch(() => {});
    }
  }, [project.id, project.has_transcript]);

  async function handleTranscribe() {
    setBusy(true);
    setError(null);
    try {
      const t = await api.transcribe(project.id);
      setTranscript(t);
      onTranscribed();
    } catch (err) {
      setError(
        err instanceof ApiError ? (err.suggestion ? `${err.message} ${err.suggestion}` : err.message) : "Transcription failed."
      );
    } finally {
      setBusy(false);
    }
  }

  async function saveEdit(segmentId: number) {
    try {
      const t = await api.editSegment(project.id, segmentId, draft);
      setTranscript(t);
    } catch {
      // keep the draft open so the user doesn't lose their edit
      return;
    }
    setEditingId(null);
  }

  if (!project.metadata) {
    return (
      <div className="rounded-2xl border border-surface-border bg-surface-raised p-6 text-sm text-slate-500">
        Add a video first.
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-surface-border bg-surface-raised p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-200">Transcript</h2>
        {!project.has_transcript && (
          <button
            onClick={handleTranscribe}
            disabled={busy}
            className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          >
            {busy ? "Transcribing..." : "Transcribe"}
          </button>
        )}
      </div>

      {error && (
        <p className="mt-3 rounded-lg border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">{error}</p>
      )}

      {!project.has_transcript && !busy && (
        <p className="mt-2 text-sm text-slate-500">
          Runs speech-to-text locally with word-level timestamps. Longer videos take longer --
          this runs synchronously for now, so the button will stay busy until it's done.
        </p>
      )}

      {transcript && (
        <div className="mt-4 max-h-96 space-y-1 overflow-y-auto pr-1">
          {transcript.segments.map((seg) => (
            <div key={seg.id} className="group rounded-lg px-2 py-1.5 hover:bg-surface">
              <div className="flex items-baseline gap-2">
                <span className="w-14 shrink-0 font-mono text-[11px] text-slate-600">{fmtTime(seg.start)}</span>
                {editingId === seg.id ? (
                  <div className="flex flex-1 gap-2">
                    <input
                      autoFocus
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && saveEdit(seg.id)}
                      className="flex-1 rounded border border-accent bg-surface px-2 py-0.5 text-sm text-slate-100 outline-none"
                    />
                    <button onClick={() => saveEdit(seg.id)} className="text-xs text-accent">
                      Save
                    </button>
                  </div>
                ) : (
                  <span
                    onClick={() => {
                      setEditingId(seg.id);
                      setDraft(seg.text);
                    }}
                    className="flex-1 cursor-text text-sm text-slate-300"
                    title="Click to edit"
                  >
                    {seg.text}
                    {seg.edited && <span className="ml-1.5 text-[10px] text-accent">edited</span>}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
