import type {
  ApiErrorPayload,
  Capabilities,
  CaptionWord,
  Clip,
  ClipsResult,
  ContentType,
  DeepPartial,
  HardwareReport,
  Job,
  Project,
  ProjectSettings,
  Transcript,
} from "./types";

// Same origin in production (the backend serves the built UI); in `npm run dev`
// Vite proxies /api to the backend (see vite.config.ts).
const API_URL: string = import.meta.env.VITE_API_URL ?? "";

export class ApiError extends Error {
  suggestion?: string;
  status: number;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.error);
    this.status = status;
    this.suggestion = payload.suggestion;
  }

  get full(): string {
    return this.suggestion ? `${this.message} ${this.suggestion}` : this.message;
  }
}

export function errorText(err: unknown, fallback = "Something went wrong."): string {
  if (err instanceof ApiError) return err.full;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(0, {
      error: "Can't reach ClipForge.",
      suggestion: "Make sure ClipForge is still running (the ClipForge window should be open), then refresh.",
    });
  }
  if (!res.ok) {
    let payload: ApiErrorPayload;
    try {
      payload = await res.json();
      if (!payload.error) payload = { error: `Request failed (${res.status}).` };
    } catch {
      payload = { error: `Request failed (${res.status}).` };
    }
    throw new ApiError(res.status, payload);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export function uploadWithProgress(
  projectId: string,
  file: File,
  onProgress: (fraction: number) => void
): Promise<Project> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/api/projects/${projectId}/upload`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as Project);
      else reject(new ApiError(xhr.status, (body as ApiErrorPayload) ?? { error: "Upload failed." }));
    };
    xhr.onerror = () =>
      reject(new ApiError(0, { error: "Upload failed.", suggestion: "Check that ClipForge is still running." }));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export const api = {
  hardware: () => request<HardwareReport>("/api/system/hardware"),
  capabilities: () => request<Capabilities>("/api/system/capabilities"),

  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (name: string, content_type: ContentType, settings?: DeepPartial<ProjectSettings>) =>
    request<Project>("/api/projects", json("POST", { name, content_type, settings })),
  updateProject: (id: string, patch: { name?: string; content_type?: ContentType }) =>
    request<Project>(`/api/projects/${id}`, json("PATCH", patch)),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),
  updateSettings: (id: string, patch: DeepPartial<ProjectSettings>) =>
    request<ProjectSettings>(`/api/projects/${id}/settings`, json("PATCH", patch)),

  process: (id: string, body: { youtube_url?: string; force_transcribe?: boolean; settings?: DeepPartial<ProjectSettings> }) =>
    request<Job>(`/api/projects/${id}/process`, json("POST", body)),
  rerank: (id: string) => request<Job>(`/api/projects/${id}/rerank`, { method: "POST" }),
  jobs: (id: string) => request<Job[]>(`/api/projects/${id}/jobs`),
  cancelJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}/cancel`, { method: "POST" }),

  mediaUrl: (id: string) => `${API_URL}/api/projects/${id}/media`,
  frameUrl: (id: string, t: number, w = 640) => `${API_URL}/api/projects/${id}/frame?t=${t.toFixed(1)}&w=${w}`,

  getTranscript: (id: string) => request<Transcript>(`/api/projects/${id}/transcript`),
  editSegment: (id: string, segmentId: number, text: string) =>
    request<Transcript>(`/api/projects/${id}/transcript/segments/${segmentId}`, json("PATCH", { text })),

  getClips: (id: string) => request<ClipsResult>(`/api/projects/${id}/clips`),
  patchClip: (
    id: string,
    clipId: string,
    patch: {
      start?: number;
      end?: number;
      title?: string;
      caption_overrides?: Record<string, unknown>;
      reframe_overrides?: Record<string, unknown>;
      clear_caption_overrides?: boolean;
      clear_reframe_overrides?: boolean;
      render?: boolean;
    }
  ) => request<Clip>(`/api/projects/${id}/clips/${clipId}`, json("PATCH", patch)),
  createClip: (id: string, body: { start: number; end: number; title?: string; render?: boolean }) =>
    request<Clip>(`/api/projects/${id}/clips`, json("POST", body)),
  deleteClip: (id: string, clipId: string) =>
    request<void>(`/api/projects/${id}/clips/${clipId}`, { method: "DELETE" }),
  renderClip: (id: string, clipId: string) => request<Job>(`/api/projects/${id}/clips/${clipId}/render`, { method: "POST" }),
  renderAll: (id: string) => request<Job[]>(`/api/projects/${id}/render-all`, { method: "POST" }),
  getWords: (id: string, clipId: string) =>
    request<{ clip_id: string; edited: boolean; words: CaptionWord[] }>(`/api/projects/${id}/clips/${clipId}/words`),
  putWords: (id: string, clipId: string, words: CaptionWord[] | null, render = false) =>
    request<{ clip_id: string; edited: boolean; words: CaptionWord[] }>(
      `/api/projects/${id}/clips/${clipId}/words`,
      json("PUT", { words, render })
    ),

  clipVideoUrl: (id: string, clipId: string, version?: string) =>
    `${API_URL}/api/projects/${id}/clips/${clipId}/video${version ? `?v=${encodeURIComponent(version)}` : ""}`,
  clipDownloadUrl: (id: string, clipId: string) => `${API_URL}/api/projects/${id}/clips/${clipId}/video?download=true`,
  clipThumbUrl: (id: string, clipId: string, version?: string) =>
    `${API_URL}/api/projects/${id}/clips/${clipId}/thumbnail${version ? `?v=${encodeURIComponent(version)}` : ""}`,
  clipSrtUrl: (id: string, clipId: string) => `${API_URL}/api/projects/${id}/clips/${clipId}/srt`,
  zipUrl: (id: string) => `${API_URL}/api/projects/${id}/clips.zip`,
  fontUrl: (name: string) => `${API_URL}/api/system/fonts/${name}`,
};
