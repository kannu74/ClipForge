import type {
  ApiErrorPayload,
  Clip,
  ClipsResult,
  ContentType,
  DurationPreset,
  HardwareReport,
  Moment,
  MomentsResult,
  Project,
  Transcript,
} from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  suggestion?: string;
  status: number;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.error);
    this.status = status;
    this.suggestion = payload.suggestion;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(0, {
      error: "Can't reach the ClipForge backend.",
      suggestion: "Make sure the backend server is running (uvicorn app.main:app) at " + API_URL + ".",
    });
  }

  if (!res.ok) {
    let payload: ApiErrorPayload;
    try {
      payload = await res.json();
    } catch {
      payload = { error: `Request failed with status ${res.status}.` };
    }
    throw new ApiError(res.status, payload);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const api = {
  health: () => request<{ status: string }>("/api/system/health"),
  hardware: () => request<HardwareReport>("/api/system/hardware"),

  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (name: string, content_type: ContentType) =>
    request<Project>("/api/projects", jsonInit("POST", { name, content_type })),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),

  uploadVideo: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Project>(`/api/projects/${id}/upload`, { method: "POST", body: form });
  },
  ingestYoutube: (id: string, url: string) =>
    request<Project>(`/api/projects/${id}/youtube`, jsonInit("POST", { url })),
  mediaUrl: (id: string) => `${API_URL}/api/projects/${id}/media`,

  transcribe: (id: string, modelSize?: string) =>
    request<Transcript>(
      `/api/projects/${id}/transcribe${modelSize ? `?model_size=${modelSize}` : ""}`,
      { method: "POST" }
    ),
  getTranscript: (id: string) => request<Transcript>(`/api/projects/${id}/transcript`),
  editSegment: (id: string, segmentId: number, text: string) =>
    request<Transcript>(
      `/api/projects/${id}/transcript/segments/${segmentId}`,
      jsonInit("PATCH", { text })
    ),

  detectMoments: (id: string) => request<MomentsResult>(`/api/projects/${id}/detect-moments`, { method: "POST" }),
  getMoments: (id: string) => request<MomentsResult>(`/api/projects/${id}/moments`),

  generateClips: (
    id: string,
    count: number,
    durationPreset: DurationPreset,
    custom?: { min: number; max: number; preferred?: number }
  ) =>
    request<ClipsResult>(
      `/api/projects/${id}/generate-clips`,
      jsonInit("POST", {
        count,
        duration_preset: durationPreset,
        custom_min_seconds: custom?.min,
        custom_max_seconds: custom?.max,
        custom_preferred_seconds: custom?.preferred,
      })
    ),
  getClips: (id: string) => request<ClipsResult>(`/api/projects/${id}/clips`),
};

export type { Moment, Clip };
