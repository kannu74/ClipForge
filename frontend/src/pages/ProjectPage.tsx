import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorText, uploadWithProgress } from "../lib/api";
import { fmtTime, isYoutubeUrl } from "../lib/format";
import {
  CONTENT_TYPE_LABELS,
  DEFAULT_SETTINGS,
  type Clip,
  type ClipsResult,
  type ContentType,
  type Job,
  type Project,
  type ProjectSettings,
} from "../lib/types";
import ClipCard from "../components/ClipCard";
import ClipEditor from "../components/ClipEditor";
import PipelineProgress from "../components/PipelineProgress";
import { CaptionControls, ClipOptions, FramingControls } from "../components/SettingsControls";
import SourceTab from "../components/SourceTab";
import TranscriptPanel from "../components/TranscriptPanel";
import { Button, Card, ErrorBox, LinkButton, ProgressBar, Segmented } from "../components/ui";

type Tab = "clips" | "source" | "transcript" | "settings";

export default function ProjectPage() {
  const { projectId = "" } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [clips, setClips] = useState<ClipsResult | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [tab, setTab] = useState<Tab>("clips");
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [editing, setEditing] = useState<Clip | null>(null);
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const lastDoneCount = useRef(-1);

  const settings: ProjectSettings = project?.settings ?? DEFAULT_SETTINGS;

  const refresh = useCallback(async () => {
    try {
      const [p, js] = await Promise.all([api.getProject(projectId), api.jobs(projectId)]);
      setProject(p);
      setJobs(js);
      if (p.has_clips) {
        setClips(await api.getClips(projectId));
      } else {
        setClips(null);
      }
    } catch (e) {
      if ((e as { status?: number }).status === 404) setNotFound(true);
      else setError(errorText(e));
    }
  }, [projectId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const activeJobs = jobs.filter((j) => j.status === "queued" || j.status === "running");
  const pipelineJob = activeJobs.find((j) => j.kind === "process" || j.kind === "rerank") ?? null;
  const renderJobs = useMemo(() => {
    // Render jobs belonging to the current batch (since the latest pipeline run).
    const latestPipeline = jobs.find((j) => j.kind === "process" || j.kind === "rerank");
    return jobs.filter((j) => j.kind === "render" && (!latestPipeline || j.created_at >= latestPipeline.created_at));
  }, [jobs]);
  const busy = activeJobs.length > 0;
  const lastPipeline = jobs.find((j) => j.kind === "process" || j.kind === "rerank");
  const failedPipeline = lastPipeline && lastPipeline.status === "failed" ? lastPipeline : null;

  // Poll while anything is running; refresh clips as renders finish.
  useEffect(() => {
    if (!busy) return;
    const id = setInterval(refresh, 1500);
    return () => clearInterval(id);
  }, [busy, refresh]);
  useEffect(() => {
    const done = jobs.filter((j) => j.status === "done").length;
    if (lastDoneCount.current !== -1 && done !== lastDoneCount.current) refresh();
    lastDoneCount.current = done;
  }, [jobs, refresh]);

  const renderJobByClip = useMemo(() => {
    const m: Record<string, Job> = {};
    for (const j of [...jobs].reverse()) {
      const cid = j.params?.clip_id as string | undefined;
      if (j.kind === "render" && cid && (j.status === "queued" || j.status === "running")) m[cid] = j;
    }
    return m;
  }, [jobs]);

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function saveSettings(patch: Partial<ProjectSettings>) {
    await act(() => api.updateSettings(projectId, patch));
  }

  if (notFound) {
    return (
      <Card className="p-8 text-center">
        <p className="text-slate-300">This project doesn't exist anymore.</p>
        <Link to="/" className="mt-3 inline-block text-accent underline">
          Back to projects
        </Link>
      </Card>
    );
  }
  if (!project) return <div className="text-sm text-slate-500">Loading...</div>;

  const hasSource = !!project.metadata;
  const clipList = clips?.clips ?? [];
  const renderedCount = clipList.filter((c) => c.render.status === "done").length;
  const staleCount = clipList.filter((c) => c.render.status === "done" && c.render.stale).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Link to="/" className="text-xs text-slate-500 hover:text-slate-300">
            ← All projects
          </Link>
          {editingName ? (
            <div className="mt-1 flex gap-2">
              <input
                autoFocus
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") act(() => api.updateProject(projectId, { name: nameDraft })).then(() => setEditingName(false));
                  if (e.key === "Escape") setEditingName(false);
                }}
                className="w-96 max-w-full rounded-lg border border-accent bg-surface px-2 py-1 text-xl font-semibold text-white outline-none"
              />
            </div>
          ) : (
            <h1
              className="mt-1 cursor-text truncate text-2xl font-semibold text-white"
              title="Click to rename"
              onClick={() => {
                setNameDraft(project.name);
                setEditingName(true);
              }}
            >
              {project.name}
            </h1>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-400">
            <select
              value={project.content_type}
              onChange={(e) => act(() => api.updateProject(projectId, { content_type: e.target.value as ContentType }))}
              className="rounded-md border border-surface-border bg-surface px-2 py-0.5 text-xs text-slate-300"
              title="Content type (used when picking clips)"
            >
              {(Object.keys(CONTENT_TYPE_LABELS) as ContentType[]).map((ct) => (
                <option key={ct} value={ct}>
                  {CONTENT_TYPE_LABELS[ct]}
                </option>
              ))}
            </select>
            {project.metadata && <span>{fmtTime(project.metadata.duration_seconds)} video</span>}
            {(settings.range_start != null || settings.range_end != null) && (
              <span className="rounded-md bg-accent/15 px-2 py-0.5 text-xs text-accent">
                Using {fmtTime(settings.range_start ?? 0)}–{settings.range_end != null ? fmtTime(settings.range_end) : "end"}
              </span>
            )}
          </div>
        </div>
        <Segmented<Tab>
          value={tab}
          onChange={setTab}
          options={[
            { value: "clips", label: `Clips${clipList.length ? ` (${clipList.length})` : ""}` },
            { value: "source", label: "Source & range" },
            { value: "transcript", label: "Transcript" },
            { value: "settings", label: "Settings" },
          ]}
        />
      </div>

      {error && <ErrorBox message={error} onDismiss={() => setError(null)} />}

      {busy && (
        <PipelineProgress
          job={pipelineJob}
          renderJobs={renderJobs}
          onCancel={pipelineJob ? () => act(() => api.cancelJob(pipelineJob.id)) : undefined}
        />
      )}

      {!busy && failedPipeline && (
        <Card className="border-red-900 p-5">
          <div className="text-sm font-semibold text-red-300">{failedPipeline.error ?? "Processing failed."}</div>
          {failedPipeline.suggestion && <div className="mt-1 text-sm text-slate-400">{failedPipeline.suggestion}</div>}
          <div className="mt-3 flex gap-2">
            <Button
              variant="primary"
              onClick={() =>
                act(() =>
                  failedPipeline.kind === "rerank"
                    ? api.rerank(projectId)
                    : api.process(projectId, {
                        youtube_url: hasSource ? undefined : ((failedPipeline.params?.youtube_url as string) ?? undefined),
                      })
                )
              }
            >
              Try again
            </Button>
          </div>
        </Card>
      )}

      {!hasSource && !busy && <AddSource project={project} onStarted={refresh} />}

      {tab === "clips" && hasSource && (
        <div className="space-y-4">
          {clips?.message && <div className="rounded-xl border border-amber-800 bg-amber-950/30 px-4 py-3 text-sm text-amber-200">{clips.message}</div>}
          {clipList.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="mr-auto text-sm text-slate-400">
                {clipList.length} clips · {renderedCount} rendered
                {staleCount > 0 && <span className="text-amber-300"> · {staleCount} need re-render</span>}
              </span>
              {renderedCount > 0 && (
                <LinkButton href={api.zipUrl(projectId)} variant="primary" download>
                  ⬇ Download all
                </LinkButton>
              )}
              {(renderedCount < clipList.length || staleCount > 0) && (
                <Button disabled={busy && !!pipelineJob} onClick={() => act(() => api.renderAll(projectId))}>
                  Render {staleCount > 0 && renderedCount === clipList.length ? "changed" : "remaining"}
                </Button>
              )}
              <Button disabled={busy} onClick={() => setTab("settings")} title="Change length / count and pick again">
                ↻ Pick clips again
              </Button>
              <Button onClick={() => setTab("source")}>+ Cut a clip</Button>
            </div>
          )}
          {clipList.length === 0 && !busy && project.has_transcript && (
            <Card className="p-8 text-center text-sm text-slate-400">
              No clips yet. <button className="text-accent underline" onClick={() => act(() => api.rerank(projectId))}>Find clips</button> or cut
              one yourself in “Source & range”.
            </Card>
          )}
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {clipList.map((c, i) => (
              <ClipCard
                key={c.id}
                projectId={projectId}
                clip={c}
                index={i}
                job={renderJobByClip[c.id]}
                onEdit={() => setEditing(c)}
                onRender={() => act(() => api.renderClip(projectId, c.id))}
                onDelete={() => {
                  if (confirm("Delete this clip?")) act(() => api.deleteClip(projectId, c.id));
                }}
              />
            ))}
          </div>
        </div>
      )}

      {tab === "source" && hasSource && (
        <SourceTab
          project={project}
          settings={settings}
          busy={busy}
          onClipAdded={() => {
            setTab("clips");
            refresh();
          }}
          onReprocess={(range) =>
            act(async () => {
              await api.updateSettings(projectId, range);
              await api.process(projectId, {});
              setTab("clips");
            })
          }
        />
      )}

      {tab === "transcript" && <TranscriptPanel project={project} onEdited={refresh} />}

      {tab === "settings" && (
        <SettingsTab
          settings={settings}
          busy={busy}
          hasTranscript={project.has_transcript}
          onSave={saveSettings}
          onRerank={() =>
            act(async () => {
              await api.rerank(projectId);
              setTab("clips");
            })
          }
          onRenderAll={() =>
            act(async () => {
              await api.renderAll(projectId);
              setTab("clips");
            })
          }
        />
      )}

      {editing && project && (
        <ClipEditor
          project={project}
          settings={settings}
          clip={clipList.find((c) => c.id === editing.id) ?? editing}
          onClose={() => setEditing(null)}
          onSaved={refresh}
        />
      )}
    </div>
  );
}

function AddSource({ project, onStarted }: { project: Project; onStarted: () => void }) {
  const [url, setUrl] = useState(project.source_type === "youtube" ? project.source_reference ?? "" : "");
  const [frac, setFrac] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <Card className="space-y-3 p-5">
      <div className="text-sm font-semibold text-slate-100">Add a video to this project</div>
      <div className="flex flex-col gap-2 md:flex-row">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="YouTube link"
          className="flex-1 rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-slate-100 outline-none focus:border-accent"
        />
        <Button
          variant="primary"
          disabled={!isYoutubeUrl(url)}
          onClick={async () => {
            setError(null);
            try {
              await api.process(project.id, { youtube_url: url.trim() });
              onStarted();
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          Download & find clips
        </Button>
        <label className="cursor-pointer rounded-lg border border-dashed border-slate-600 px-3 py-2 text-center text-sm text-slate-300 hover:border-accent">
          Upload file
          <input
            type="file"
            accept="video/*,.mkv,.flv,.ts,.mts"
            className="hidden"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              setError(null);
              try {
                setFrac(0);
                await uploadWithProgress(project.id, f, setFrac);
                await api.process(project.id, {});
                setFrac(null);
                onStarted();
              } catch (err) {
                setFrac(null);
                setError(errorText(err));
              }
            }}
          />
        </label>
      </div>
      {frac !== null && <ProgressBar value={frac} />}
      {error && <ErrorBox message={error} onDismiss={() => setError(null)} />}
    </Card>
  );
}

function SettingsTab({
  settings,
  busy,
  hasTranscript,
  onSave,
  onRerank,
  onRenderAll,
}: {
  settings: ProjectSettings;
  busy: boolean;
  hasTranscript: boolean;
  onSave: (patch: Partial<ProjectSettings>) => Promise<void>;
  onRerank: () => void;
  onRenderAll: () => void;
}) {
  const [draft, setDraft] = useState<ProjectSettings>(settings);
  const [section, setSection] = useState<"clips" | "captions" | "framing">("clips");
  useEffect(() => setDraft(settings), [settings]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(settings);
  const clipsChanged =
    draft.clip_count !== settings.clip_count ||
    draft.duration_preset !== settings.duration_preset ||
    draft.custom_min_seconds !== settings.custom_min_seconds ||
    draft.custom_max_seconds !== settings.custom_max_seconds ||
    draft.include_backup_clips !== settings.include_backup_clips;

  return (
    <Card className="space-y-5 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented
          size="sm"
          value={section}
          onChange={setSection}
          options={[
            { value: "clips", label: "Clips" },
            { value: "captions", label: "Captions" },
            { value: "framing", label: "Framing & quality" },
          ]}
        />
        <span className="text-xs text-slate-500">
          Project defaults. A clip you've customised in its editor keeps its own settings.
        </span>
      </div>
      {section === "clips" && <ClipOptions value={draft} onChange={(p) => setDraft((d) => ({ ...d, ...p }))} />}
      {section === "captions" && (
        <CaptionControls value={draft.captions} onChange={(p) => setDraft((d) => ({ ...d, captions: { ...d.captions, ...p } }))} />
      )}
      {section === "framing" && (
        <div className="space-y-5">
          <FramingControls value={draft.reframe} onChange={(p) => setDraft((d) => ({ ...d, reframe: { ...d.reframe, ...p } }))} />
          <div className="grid gap-5 md:grid-cols-2">
            <div className="space-y-1.5">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Resolution</div>
              <Segmented
                size="sm"
                value={draft.render.resolution}
                onChange={(v) => setDraft((d) => ({ ...d, render: { ...d.render, resolution: v } }))}
                options={[
                  { value: 1080, label: "1080p" },
                  { value: 720, label: "720p (faster)" },
                ]}
              />
            </div>
            <div className="space-y-1.5">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Render quality</div>
              <Segmented
                size="sm"
                value={draft.render.quality}
                onChange={(v) => setDraft((d) => ({ ...d, render: { ...d.render, quality: v } }))}
                options={[
                  { value: "fast", label: "Fast" },
                  { value: "balanced", label: "Balanced" },
                  { value: "high", label: "High" },
                ]}
              />
            </div>
          </div>
        </div>
      )}
      <div className="flex flex-wrap gap-2 border-t border-surface-border pt-4">
        <Button variant="primary" disabled={!dirty} onClick={() => onSave(draft)}>
          Save settings
        </Button>
        <Button
          disabled={busy || !hasTranscript}
          onClick={async () => {
            if (dirty) await onSave(draft);
            onRerank();
          }}
          title="Re-pick clips with these settings (keeps your manual clips; no re-transcription)"
        >
          {clipsChanged ? "Save & pick clips again" : "Pick clips again"}
        </Button>
        <Button
          disabled={busy}
          onClick={async () => {
            if (dirty) await onSave(draft);
            onRenderAll();
          }}
          title="Re-render every clip whose look changed"
        >
          Save & re-render changed clips
        </Button>
      </div>
    </Card>
  );
}
