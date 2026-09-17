import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { CONTENT_TYPE_LABELS, type Project } from "../lib/types";

export default function ProjectDetail() {
  const { projectId } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    api
      .getProject(projectId)
      .then(setProject)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load project."));
  }, [projectId]);

  if (error) {
    return (
      <div className="rounded-lg border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">
        {error}{" "}
        <Link to="/" className="underline">
          Back to projects
        </Link>
      </div>
    );
  }

  if (!project) {
    return <div className="text-sm text-slate-500">Loading...</div>;
  }

  return (
    <div>
      <Link to="/" className="text-xs text-slate-500 hover:text-slate-300">
        ← All projects
      </Link>
      <h1 className="mt-2 text-2xl font-semibold text-slate-100">{project.name}</h1>
      <p className="mt-1 text-sm text-slate-400">
        {CONTENT_TYPE_LABELS[project.content_type]} · status: {project.status}
      </p>

      <div className="mt-10 rounded-2xl border border-dashed border-surface-border p-10 text-center">
        <p className="text-slate-300">Video ingestion isn't built yet.</p>
        <p className="mt-1 text-sm text-slate-500">
          This is Phase 0 (foundation) -- project creation and storage work, but uploading a
          video or pasting a YouTube URL comes in Phase 1. Check{" "}
          <code className="rounded bg-surface-raised px-1 py-0.5 text-xs">
            DEVELOPMENT_PROGRESS.md
          </code>{" "}
          for current status.
        </p>
      </div>
    </div>
  );
}
