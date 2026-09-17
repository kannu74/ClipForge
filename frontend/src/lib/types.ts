export type ContentType =
  | "gaming"
  | "funny_gaming"
  | "horror_gaming"
  | "reaction"
  | "comedy"
  | "commentary"
  | "storytelling"
  | "general_creator";

export const CONTENT_TYPE_LABELS: Record<ContentType, string> = {
  gaming: "Gaming",
  funny_gaming: "Funny Gaming",
  horror_gaming: "Horror Gaming",
  reaction: "Reaction",
  comedy: "Comedy",
  commentary: "Commentary",
  storytelling: "Storytelling",
  general_creator: "General Creator",
};

export interface Project {
  id: string;
  name: string;
  content_type: ContentType;
  source_type: "local" | "youtube" | null;
  source_reference: string | null;
  status: string;
  preset_id: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface GpuInfo {
  available: boolean;
  name: string | null;
  vram_total_mb: number | null;
  vram_free_mb: number | null;
  cuda_available: boolean;
}

export interface HardwareReport {
  cpu_cores_logical: number;
  cpu_cores_physical: number | null;
  ram_total_mb: number;
  ram_available_mb: number;
  gpu: GpuInfo;
  ffmpeg_available: boolean;
  ffmpeg_version: string | null;
  ollama_reachable: boolean;
  ollama_models: string[];
  recommended_quality_mode: string;
}

export interface ApiErrorPayload {
  error: string;
  suggestion?: string;
}
