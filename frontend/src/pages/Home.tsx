import { useEffect, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorText, uploadWithProgress } from "../lib/api";
import { cx, fmtDuration, isYoutubeUrl, parseTime, timeAgo } from "../lib/format";
import {
  CONTENT_TYPE_LABELS,
  DEFAULT_SETTINGS,
  type ContentType,
  type Preset,
  type ProjectSettings,
  type Project,
} from "../lib/types";
import { CaptionControls, ClipOptions, FramingControls } from "../components/SettingsControls";
import { Button, CaptionsOnOff, Card, ErrorBox, ProgressBar, Segmented, TimeInput, Toggle } from "../components/ui";

const PREFS_KEY = "clipforge.lastSettings.v1";

function loadPrefs(): { settings: ProjectSettings; contentType: ContentType } {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) {
      const p = JSON.parse(raw);
      return {
        settings: {
          ...DEFAULT_SETTINGS,
          ...p.settings,
          captions: { ...DEFAULT_SETTINGS.captions, ...(p.settings?.captions ?? {}) },
          reframe: { ...DEFAULT_SETTINGS.reframe, ...(p.settings?.reframe ?? {}), facecam: null },
          render: { ...DEFAULT_SETTINGS.render, ...(p.settings?.render ?? {}) },
          range_start: null,
          range_end: null,
        },
        contentType: p.contentType ?? "gaming",
      };
    }
  } catch {
    /* storage unavailable -- use defaults */
  }
  return { settings: DEFAULT_SETTINGS, contentType: "gaming" };
}

function savePrefs(settings: ProjectSettings, contentType: ContentType) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify({ settings, contentType }));
  } catch {
    /* ignore */
  }
}

export default function Home() {
  const navigate = useNavigate();
  const prefs = useRef(loadPrefs()).current;
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [contentType, setContentType] = useState<ContentType>(prefs.contentType);
  const [settings, setSettings] = useState<ProjectSettings>(prefs.settings);
  const [tab, setTab] = useState<"clips" | "captions" | "framing">("clips");
  const [useRange, setUseRange] = useState(false);
  const [rangeStart, setRangeStart] = useState("");
  const [rangeEnd, setRangeEnd] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploadFrac, setUploadFrac] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.listProjects().then(setProjects).catch((e) => setError(errorText(e)));
    api.listPresets().then(setPresets).catch(() => {});
  }, []);

  function applyPreset(p: Preset) {
    const ps = p.settings as Partial<ProjectSettings>;
    setSettings({
      ...DEFAULT_SETTINGS,
      ...ps,
      captions: { ...DEFAULT_SETTINGS.captions, ...(ps.captions ?? {}) },
      reframe: { ...DEFAULT_SETTINGS.reframe, ...(ps.reframe ?? {}), facecam: null },
      render: { ...DEFAULT_SETTINGS.render, ...(ps.render ?? {}) },
      range_start: null,
      range_end: null,
    } as ProjectSettings);
    setContentType(p.content_type);
    setActivePreset(p.id);
  }

  async function saveAsPreset() {
    const name = prompt("Name this preset (e.g. “My horror shorts”):");
    if (!name?.trim()) return;
    try {
      const p = await api.createPreset(name.trim(), contentType, settings);
      setPresets((ps) => [...ps, p]);
      setActivePreset(p.id);
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function removePreset(p: Preset) {
    if (!confirm(`Delete the preset “${p.name}”?`)) return;
    try {
      await api.deletePreset(p.id);
      setPresets((ps) => ps.filter((x) => x.id !== p.id));
    } catch (e) {
      setError(errorText(e));
    }
  }

  const urlValid = isYoutubeUrl(url);
  const canStart = !busy && (file !== null || urlValid);

  function patch(p: Partial<ProjectSettings>) {
    setSettings((s) => ({ ...s, ...p }));
    setActivePreset(null);
  }

  async function start() {
    setError(null);
    let range_start: number | null = null;
    let range_end: number | null = null;
    if (useRange) {
      range_start = rangeStart ? parseTime(rangeStart) : null;
      range_end = rangeEnd ? parseTime(rangeEnd) : null;
      if ((rangeStart && range_start === null) || (rangeEnd && range_end === null)) {
        setError("Couldn't read the start/end time. Use minutes:seconds, e.g. 12:30.");
        return;
      }
      if (range_start !== null && range_end !== null && range_end - range_start < 10) {
        setError("The selected part must be at least 10 seconds long.");
        return;
      }
    }
    const finalSettings = { ...settings, range_start, range_end };
    savePrefs(settings, contentType);
    setBusy(true);
    try {
      if (file) {
        const name = file.name.replace(/\.[^.]+$/, "") || "My video";
        const project = await api.createProject(name, contentType, finalSettings);
        setUploadFrac(0);
        await uploadWithProgress(project.id, file, setUploadFrac);
        await api.process(project.id, {});
        navigate(`/projects/${project.id}`);
      } else {
        const project = await api.createProject("YouTube video", contentType, finalSettings);
        await api.process(project.id, { youtube_url: url.trim() });
        navigate(`/projects/${project.id}`);
      }
    } catch (e) {
      setError(errorText(e, "Couldn't start processing."));
      setBusy(false);
      setUploadFrac(null);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) {
      setFile(f);
      setUrl("");
    }
  }

  async function removeProject(p: Project) {
    if (!confirm(`Delete "${p.name}" and all its clips? This can't be undone.`)) return;
    try {
      await api.deleteProject(p.id);
      setProjects((ps) => (ps ?? []).filter((x) => x.id !== p.id));
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <div className="space-y-10">
      <section className="mx-auto max-w-3xl pt-6 text-center">
        <h1 className="text-4xl font-bold tracking-tight text-white md:text-5xl">
          Long video in. <span className="bg-gradient-to-r from-accent to-fuchsia-400 bg-clip-text text-transparent">Viral clips out.</span>
        </h1>
        <p className="mt-3 text-slate-400">
          Finds the best moments, cuts them cleanly, adds Hinglish-friendly captions and reframes for Shorts / Reels — all on your own computer.
        </p>
      </section>

      <Card className="mx-auto max-w-3xl p-5">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className={cx("rounded-xl transition-colors", dragOver && "bg-accent/10 ring-2 ring-accent")}
        >
          <div className="flex flex-col gap-3 md:flex-row">
            <input
              value={file ? "" : url}
              onChange={(e) => {
                setUrl(e.target.value);
                setFile(null);
              }}
              disabled={!!file || busy}
              placeholder={file ? file.name : "Paste a YouTube link (video, live or shorts)"}
              className="flex-1 rounded-xl border border-surface-border bg-surface px-4 py-3 text-base text-slate-100 outline-none placeholder:text-slate-500 focus:border-accent"
              onKeyDown={(e) => e.key === "Enter" && canStart && start()}
            />
            <Button variant="primary" size="lg" disabled={!canStart} onClick={start}>
              {busy ? "Starting..." : "Get clips"}
            </Button>
          </div>
          <div className="mt-3 flex items-center justify-center gap-3 text-sm text-slate-500">
            <span>or</span>
            <button
              type="button"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
              className="rounded-lg border border-dashed border-slate-600 px-4 py-2 text-slate-300 hover:border-accent hover:text-white"
            >
              {file ? `📁 ${file.name}` : "Upload a video file (or drop it here)"}
            </button>
            {file && (
              <button type="button" onClick={() => setFile(null)} className="text-xs text-slate-500 hover:text-slate-200">
                remove
              </button>
            )}
            <input
              ref={fileInput}
              type="file"
              accept="video/*,.mkv,.flv,.ts,.mts"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) {
                  setFile(f);
                  setUrl("");
                }
              }}
            />
          </div>
          {url && !urlValid && !file && (
            <p className="mt-2 text-center text-xs text-amber-400">That doesn't look like a YouTube video link.</p>
          )}
        </div>

        {uploadFrac !== null && (
          <div className="mt-4">
            <div className="mb-1 flex justify-between text-xs text-slate-400">
              <span>Uploading {file?.name}</span>
              <span>{Math.round(uploadFrac * 100)}%</span>
            </div>
            <ProgressBar value={uploadFrac} />
          </div>
        )}

        {error && (
          <div className="mt-4">
            <ErrorBox message={error} onDismiss={() => setError(null)} />
          </div>
        )}

        {presets.length > 0 && (
          <div className="mt-6 space-y-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Start from a preset</div>
            <div className="flex flex-wrap gap-2">
              {presets.map((p) => (
                <span
                  key={p.id}
                  className={cx(
                    "group inline-flex items-center gap-1 rounded-full border px-3 py-1 text-sm transition-colors",
                    activePreset === p.id ? "border-fuchsia-400 bg-fuchsia-500/15 text-white" : "border-surface-border text-slate-300 hover:text-white"
                  )}
                >
                  <button type="button" onClick={() => applyPreset(p)}>
                    {p.builtin ? "✨ " : ""}
                    {p.name}
                  </button>
                  {!p.builtin && (
                    <button type="button" onClick={() => removePreset(p)} className="ml-1 hidden text-xs text-slate-500 hover:text-red-300 group-hover:inline" title="Delete preset">
                      ✕
                    </button>
                  )}
                </span>
              ))}
              <button type="button" onClick={saveAsPreset} className="rounded-full border border-dashed border-slate-600 px-3 py-1 text-sm text-slate-400 hover:text-white">
                ＋ Save current settings
              </button>
            </div>
          </div>
        )}

        <div className="mt-6 space-y-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">What kind of video is it?</div>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(CONTENT_TYPE_LABELS) as ContentType[]).map((ct) => (
              <button
                key={ct}
                type="button"
                onClick={() => {
                  setContentType(ct);
                  setActivePreset(null);
                }}
                className={cx(
                  "rounded-full border px-3 py-1 text-sm transition-colors",
                  contentType === ct ? "border-accent bg-accent/15 text-white" : "border-surface-border text-slate-400 hover:text-slate-200"
                )}
              >
                {CONTENT_TYPE_LABELS[ct]}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-6 space-y-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Captions</div>
          <CaptionsOnOff
            enabled={settings.captions.enabled}
            onChange={(v) => patch({ captions: { ...settings.captions, enabled: v } })}
          />
        </div>

        <div className="mt-6 rounded-xl border border-surface-border bg-surface/50 p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <Segmented
              size="sm"
              value={tab}
              onChange={setTab}
              options={[
                { value: "clips", label: "Clips" },
                { value: "captions", label: "Captions" },
                { value: "framing", label: "Framing" },
              ]}
            />
            <span className="text-xs text-slate-500">Remembered for next time. Every clip can be edited afterwards.</span>
          </div>
          {tab === "clips" && (
            <div className="space-y-5">
              <ClipOptions value={settings} onChange={patch} />
              <div className="space-y-2">
                <Toggle checked={useRange} onChange={setUseRange} label="Only use part of the video" />
                {useRange && (
                  <div className="flex flex-wrap items-center gap-2 pl-11 text-sm text-slate-400">
                    from <TimeInput value={rangeStart} onChange={setRangeStart} placeholder="0:00" /> to{" "}
                    <TimeInput value={rangeEnd} onChange={setRangeEnd} placeholder="end" />
                    <span className="text-xs text-slate-500">(e.g. 12:30 – 45:00 of a long stream; you can also change this later)</span>
                  </div>
                )}
              </div>
            </div>
          )}
          {tab === "captions" && (
            <CaptionControls value={settings.captions} onChange={(p) => patch({ captions: { ...settings.captions, ...p } })} />
          )}
          {tab === "framing" && (
            <FramingControls value={settings.reframe} onChange={(p) => patch({ reframe: { ...settings.reframe, ...p } })} />
          )}
        </div>
      </Card>

      <section className="mx-auto max-w-6xl">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Your projects</h2>
        {projects === null ? (
          <div className="text-sm text-slate-500">Loading...</div>
        ) : projects.length === 0 ? (
          <div className="rounded-xl border border-dashed border-surface-border p-8 text-center text-sm text-slate-500">
            No projects yet — paste a link or upload a video above.
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <div key={p.id} className="group relative overflow-hidden rounded-2xl border border-surface-border bg-surface-raised hover:border-slate-500">
                <Link to={`/projects/${p.id}`} className="block">
                  <div className="aspect-video bg-surface">
                    {p.metadata ? (
                      <img
                        src={api.frameUrl(p.id, Math.min(30, (p.metadata.duration_seconds || 10) * 0.1), 480)}
                        alt=""
                        className="h-full w-full object-cover opacity-90 group-hover:opacity-100"
                        loading="lazy"
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center text-xs text-slate-600">No video yet</div>
                    )}
                  </div>
                  <div className="p-3">
                    <div className="truncate text-sm font-medium text-slate-100">{p.name}</div>
                    <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                      <span>{CONTENT_TYPE_LABELS[p.content_type] ?? p.content_type}</span>
                      {p.metadata && <span>· {fmtDuration(p.metadata.duration_seconds)}</span>}
                      <span>· {timeAgo(p.created_at)}</span>
                      <StatusDot status={p.status} hasClips={p.has_clips} />
                    </div>
                  </div>
                </Link>
                <button
                  onClick={() => removeProject(p)}
                  className="absolute right-2 top-2 hidden rounded-lg bg-black/70 px-2 py-1 text-xs text-slate-300 hover:text-red-300 group-hover:block"
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function StatusDot({ status, hasClips }: { status: string; hasClips: boolean }) {
  if (status === "error") return <span className="text-red-400">· failed</span>;
  if (["processing", "ingesting", "transcribing", "analyzing", "queued"].includes(status))
    return <span className="text-accent">· working...</span>;
  if (hasClips) return <span className="text-emerald-400">· clips ready</span>;
  return null;
}
