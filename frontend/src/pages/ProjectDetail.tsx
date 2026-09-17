import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { CONTENT_TYPE_LABELS, type Project } from "../lib/types";
import SourcePanel from "../components/SourcePanel";
import TranscriptPanel from "../components/TranscriptPanel";
import MomentsPanel from "../components/MomentsPanel";

export default function ProjectDetail() {
  const { projectId } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  const refresh = useCallback(() => {
    if (!projectId) return;
    api
      .getProject(projectId)
      .then(setProject)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load project."));
  }, [projectId]);

  useEffect(refresh, [refresh]);

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
      {project.status === "error" && project.error_message && (
        <p className="mt-2 rounded-lg border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">
          {project.error_message}
        </p>
      )}

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="space-y-6">
          <SourcePanel project={project} onUpdated={setProject} videoRef={videoRef} />
          <MomentsPanel project={project} videoRef={videoRef} />
        </div>
        <TranscriptPanel project={project} onTranscribed={refresh} />
      </div>
    </div>
  );
}
