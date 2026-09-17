import type { ApiErrorPayload, ContentType, HardwareReport, Project } from "./types";

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
    res = await fetch(`${API_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
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

export const api = {
  health: () => request<{ status: string }>("/api/system/health"),
  hardware: () => request<HardwareReport>("/api/system/hardware"),
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (name: string, content_type: ContentType) =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, content_type }),
    }),
  deleteProject: (id: string) =>
    request<void>(`/api/projects/${id}`, { method: "DELETE" }),
};
