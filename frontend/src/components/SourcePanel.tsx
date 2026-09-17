import { useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import type { Project } from "../lib/types";

interface Props {
  project: Project;
  onUpdated: (project: Project) => void;
  videoRef: React.RefObject<HTMLVideoElement>;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

export default function SourcePanel({ project, onUpdated, videoRef }: Props) {
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleUpload(file: File) {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.uploadVideo(project.id, file);
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof ApiError ? (err.suggestion ? `${err.message} ${err.suggestion}` : err.message) : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleYoutubeSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const updated = await api.ingestYoutube(project.id, youtubeUrl);
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof ApiError ? (err.suggestion ? `${err.message} ${err.suggestion}` : err.message) : "Couldn't fetch that video.");
    } finally {
      setBusy(false);
    }
  }

  if (!project.metadata) {
    return (
      <div className="rounded-2xl border border-surface-border bg-surface-raised p-6">
        <h2 className="text-sm font-semibold text-slate-200">Add a video</h2>
        <p className="mt-1 text-sm text-slate-500">Upload a local file, or paste a YouTube URL.</p>

        <label className="mt-4 flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-surface-border px-6 py-8 text-center hover:border-accent/60">
          <span className="text-sm text-slate-300">Click to choose a video file</span>
          <span className="mt-1 text-xs text-slate-500">MP4, MOV, MKV, WebM, AVI</span>
          <input
            type="file"
            accept=".mp4,.mov,.mkv,.webm,.avi"
            className="hidden"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleUpload(file);
            }}
          />
        </label>

        <div className="my-4 flex items-center gap-3 text-xs text-slate-600">
          <div className="h-px flex-1 bg-surface-border" />
          OR
          <div className="h-px flex-1 bg-surface-border" />
        </div>

        <form onSubmit={handleYoutubeSubmit} className="flex gap-2">
          <input
            value={youtubeUrl}
            onChange={(e) => setYoutubeUrl(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=..."
            disabled={busy}
            className="flex-1 rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-slate-100 outline-none focus:border-accent"
          />
          <button
            type="submit"
            disabled={busy || !youtubeUrl.trim()}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            Fetch
          </button>
        </form>

        {busy && <p className="mt-3 text-xs text-slate-500">Processing... this can take a while for YouTube videos.</p>}
        {error && (
          <p className="mt-3 rounded-lg border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">{error}</p>
        )}
      </div>
    );
  }

  const m = project.metadata;
  return (
    <div className="rounded-2xl border border-surface-border bg-surface-raised p-4">
      <video ref={videoRef} controls className="w-full rounded-xl bg-black" src={api.mediaUrl(project.id)} />
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        <span>{formatDuration(m.duration_seconds)}</span>
        <span>
          {m.width}x{m.height} ({m.aspect_ratio})
        </span>
        <span>{m.fps} fps</span>
        <span>{m.video_codec ?? "unknown codec"}</span>
        {m.has_audio && <span>{m.audio_codec ?? "unknown audio"}</span>}
        {!m.has_audio && <span className="text-amber-400">no audio track</span>}
        <span>{formatBytes(m.file_size_bytes)}</span>
        <span className="text-slate-600">
          {project.source_type === "youtube" ? "from YouTube" : "uploaded"}
        </span>
      </div>
    </div>
  );
}
