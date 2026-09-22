import { useEffect, useState } from "react";
import { api, errorText } from "../lib/api";
import { fmtTime } from "../lib/format";
import type { Project, Transcript } from "../lib/types";
import { Card, ErrorBox } from "./ui";

export default function TranscriptPanel({ project, onEdited }: { project: Project; onEdited: () => void }) {
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (project.has_transcript) {
      api.getTranscript(project.id).then(setTranscript).catch((e) => setError(errorText(e)));
    }
  }, [project.id, project.has_transcript]);

  async function saveEdit(segmentId: number) {
    try {
      const t = await api.editSegment(project.id, segmentId, draft);
      setTranscript(t);
      setEditingId(null);
      onEdited();
    } catch (e) {
      setError(errorText(e));
    }
  }

  if (!project.has_transcript) {
    return <Card className="p-6 text-sm text-slate-500">The transcript appears here once the video has been processed.</Card>;
  }

  const q = query.trim().toLowerCase();
  const segments = (transcript?.segments ?? []).filter((s) => !q || s.text.toLowerCase().includes(q));

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">Transcript</h2>
          {transcript && (
            <p className="text-xs text-slate-500">
              {transcript.segments.length} segments · language: {transcript.language ?? "unknown"} · model: {transcript.model_size}.
              Click a line to fix it — rendered clips using it will be marked for re-render.
            </p>
          )}
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search..."
          className="w-48 rounded-lg border border-surface-border bg-surface px-3 py-1.5 text-sm text-slate-100 outline-none focus:border-accent"
        />
      </div>
      {error && (
        <div className="mt-3">
          <ErrorBox message={error} onDismiss={() => setError(null)} />
        </div>
      )}
      <div className="mt-4 max-h-[65vh] space-y-0.5 overflow-y-auto pr-1">
        {segments.map((seg) => (
          <div key={seg.id} className="group rounded-lg px-2 py-1.5 hover:bg-surface">
            <div className="flex items-baseline gap-3">
              <span className="w-16 shrink-0 font-mono text-[11px] text-slate-600">{fmtTime(seg.start)}</span>
              {editingId === seg.id ? (
                <div className="flex flex-1 gap-2">
                  <input
                    autoFocus
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") saveEdit(seg.id);
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    className="flex-1 rounded border border-accent bg-surface px-2 py-0.5 text-sm text-slate-100 outline-none"
                  />
                  <button onClick={() => saveEdit(seg.id)} className="text-xs font-semibold text-accent">
                    Save
                  </button>
                  <button onClick={() => setEditingId(null)} className="text-xs text-slate-500">
                    Cancel
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
    </Card>
  );
}
