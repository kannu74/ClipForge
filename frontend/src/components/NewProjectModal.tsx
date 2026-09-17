import { useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { CONTENT_TYPE_LABELS, type ContentType, type Project } from "../lib/types";

const CONTENT_TYPES = Object.keys(CONTENT_TYPE_LABELS) as ContentType[];

interface Props {
  onClose: () => void;
  onCreated: (project: Project) => void;
}

export default function NewProjectModal({ onClose, onCreated }: Props) {
  const [name, setName] = useState("");
  const [contentType, setContentType] = useState<ContentType>("gaming");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const project = await api.createProject(name, contentType);
      onCreated(project);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.suggestion ? `${err.message} ${err.suggestion}` : err.message);
      } else {
        setError("Something went wrong creating the project.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-2xl border border-surface-border bg-surface-raised p-6 shadow-2xl"
      >
        <h2 className="text-lg font-semibold text-slate-100">New project</h2>
        <p className="mt-1 text-sm text-slate-400">
          Give it a name and tell ClipForge what kind of content this is -- that changes how
          moments get evaluated later.
        </p>

        <label className="mt-5 block text-xs font-medium uppercase tracking-wide text-slate-500">
          Project name
        </label>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Valorant Ranked Rage Compilation"
          className="mt-1.5 w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-slate-100 outline-none focus:border-accent"
        />

        <label className="mt-4 block text-xs font-medium uppercase tracking-wide text-slate-500">
          Content type
        </label>
        <select
          value={contentType}
          onChange={(e) => setContentType(e.target.value as ContentType)}
          className="mt-1.5 w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-slate-100 outline-none focus:border-accent"
        >
          {CONTENT_TYPES.map((ct) => (
            <option key={ct} value={ct}>
              {CONTENT_TYPE_LABELS[ct]}
            </option>
          ))}
        </select>

        {error && (
          <p className="mt-3 rounded-lg border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-slate-200"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!name.trim() || submitting}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "Creating..." : "Create project"}
          </button>
        </div>
      </form>
    </div>
  );
}
