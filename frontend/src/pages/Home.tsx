import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { CONTENT_TYPE_LABELS, type Project } from "../lib/types";
import NewProjectModal from "../components/NewProjectModal";

function statusColor(status: string) {
  if (status === "error") return "bg-red-500";
  if (status === "ready") return "bg-emerald-500";
  if (status === "created") return "bg-slate-500";
  return "bg-amber-400";
}

export default function Home() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);

  function refresh() {
    api
      .listProjects()
      .then(setProjects)
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "Failed to load projects.");
      });
  }

  useEffect(refresh, []);

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Projects</h1>
          <p className="mt-1 text-sm text-slate-400">
            Upload a video or paste a YouTube URL, and ClipForge will find, cut, caption and
            reframe the strongest short-form clips -- entirely on this machine.
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
        >
          + New project
        </button>
      </div>

      {error && (
        <div className="mt-6 rounded-lg border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {!error && projects === null && (
        <div className="mt-10 text-sm text-slate-500">Loading projects...</div>
      )}

      {projects && projects.length === 0 && (
        <div className="mt-16 flex flex-col items-center justify-center rounded-2xl border border-dashed border-surface-border py-20 text-center">
          <p className="text-slate-400">No projects yet.</p>
          <button
            onClick={() => setShowModal(true)}
            className="mt-4 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
          >
            Create your first project
          </button>
        </div>
      )}

      {projects && projects.length > 0 && (
        <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <Link
              key={p.id}
              to={`/projects/${p.id}`}
              className="group rounded-xl border border-surface-border bg-surface-raised p-4 transition hover:border-accent/60"
            >
              <div className="flex items-center justify-between">
                <span className="truncate text-sm font-medium text-slate-100">{p.name}</span>
                <span className={`h-2 w-2 shrink-0 rounded-full ${statusColor(p.status)}`} />
              </div>
              <div className="mt-2 text-xs text-slate-500">
                {CONTENT_TYPE_LABELS[p.content_type]} · {p.status}
              </div>
              <div className="mt-3 text-[11px] text-slate-600">
                Created {new Date(p.created_at).toLocaleString()}
              </div>
            </Link>
          ))}
        </div>
      )}

      {showModal && (
        <NewProjectModal
          onClose={() => setShowModal(false)}
          onCreated={(project) => {
            setShowModal(false);
            setProjects((prev) => [project, ...(prev ?? [])]);
          }}
        />
      )}
    </div>
  );
}
