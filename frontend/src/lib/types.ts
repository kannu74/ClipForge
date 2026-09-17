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

export interface MediaMetadata {
  duration_seconds: number;
  width: number;
  height: number;
  fps: number;
  video_codec: string | null;
  audio_codec: string | null;
  audio_channels: number | null;
  has_audio: boolean;
  file_size_bytes: number;
  aspect_ratio: string;
}

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
  metadata: MediaMetadata | null;
  has_transcript: boolean;
  has_moments: boolean;
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

export interface TranscriptWord {
  word: string;
  start: number;
  end: number;
  probability: number | null;
}

export interface TranscriptSegment {
  id: number;
  start: number;
  end: number;
  text: string;
  words: TranscriptWord[];
  edited: boolean;
}

export interface Transcript {
  project_id: string;
  language: string | null;
  model_size: string;
  segments: TranscriptSegment[];
  created_at: string;
}

export interface Moment {
  id: string;
  start: number;
  end: number;
  category: string;
  score: number;
  signals: Record<string, unknown>;
  transcript_excerpt: string;
  reason: string;
  llm_enriched: boolean;
}

export interface MomentsResult {
  project_id: string;
  content_type: string;
  moments: Moment[];
  ollama_used: boolean;
  created_at: string;
}
