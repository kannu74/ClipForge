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
  funny_gaming: "Funny gaming",
  horror_gaming: "Horror gaming",
  reaction: "Reaction",
  comedy: "Comedy",
  commentary: "Commentary",
  storytelling: "Storytelling",
  general_creator: "General",
};

export type DurationPreset = "ultra_short" | "short" | "standard" | "extended" | "custom";

export const DURATION_PRESET_LABELS: Record<DurationPreset, string> = {
  ultra_short: "10–20s",
  short: "20–35s",
  standard: "30–60s",
  extended: "60–90s",
  custom: "Custom",
};

export type CaptionStyleName = "bold_pop" | "karaoke" | "clean" | "boxed" | "horror" | "neon" | "none";
export type CaptionPosition = "top" | "upper" | "middle" | "lower" | "bottom";
export type CaptionScript = "as_spoken" | "roman" | "devanagari";
export type ReframeMode = "auto" | "fill" | "fit_blur" | "track" | "split" | "original";
export type AspectRatio = "9:16" | "1:1" | "4:5" | "16:9";

export interface CaptionSettings {
  enabled: boolean;
  style: CaptionStyleName;
  position: CaptionPosition;
  font_scale: number;
  words_per_line: number;
  max_lines: number;
  uppercase: boolean;
  text_color: string;
  highlight_color: string;
  outline_color: string;
  font: string;
  script: CaptionScript;
  emphasize_keywords: boolean;
  title_overlay: boolean;
  title_seconds: number;
}

export interface FacecamRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ReframeSettings {
  aspect: AspectRatio;
  mode: ReframeMode;
  facecam: FacecamRect | null;
  split_ratio: number;
  facecam_on_top: boolean;
  focus_x: number;
}

export interface RenderSettings {
  resolution: 720 | 1080;
  quality: "fast" | "balanced" | "high";
}

export interface ProjectSettings {
  clip_count: number;
  duration_preset: DurationPreset;
  custom_min_seconds: number | null;
  custom_max_seconds: number | null;
  range_start: number | null;
  range_end: number | null;
  whisper_model: string | null;
  language: string;
  auto_render: boolean;
  include_backup_clips: boolean;
  captions: CaptionSettings;
  reframe: ReframeSettings;
  render: RenderSettings;
}

export type DeepPartial<T> = { [K in keyof T]?: T[K] extends object | null ? DeepPartial<NonNullable<T[K]>> | T[K] : T[K] };

export const DEFAULT_SETTINGS: ProjectSettings = {
  clip_count: 8,
  duration_preset: "standard",
  custom_min_seconds: null,
  custom_max_seconds: null,
  range_start: null,
  range_end: null,
  whisper_model: null,
  language: "",
  auto_render: true,
  include_backup_clips: true,
  captions: {
    enabled: true,
    style: "bold_pop",
    position: "lower",
    font_scale: 1,
    words_per_line: 3,
    max_lines: 1,
    uppercase: true,
    text_color: "#FFFFFF",
    highlight_color: "#FFE14D",
    outline_color: "#000000",
    font: "",
    script: "as_spoken",
    emphasize_keywords: true,
    title_overlay: false,
    title_seconds: 3,
  },
  reframe: { aspect: "9:16", mode: "auto", facecam: null, split_ratio: 0.4, facecam_on_top: true, focus_x: 0.5 },
  render: { resolution: 1080, quality: "balanced" },
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
  has_clips: boolean;
  settings: ProjectSettings | null;
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

export interface Capabilities {
  gpu_transcription?: { nvidia_gpu: boolean; cuda_libs_installed: boolean };
  ffmpeg: { available: boolean; version: string | null; captions_supported: boolean; nvenc: boolean };
  face_detection: boolean;
  youtube: { yt_dlp: string | null; js_runtime: boolean };
  whisper: { default_model: string; models: string[]; device: string; faster_whisper: string | null };
  caption_styles: string[];
  reframe_modes: Record<string, string>;
  version: string;
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

export interface QcReport {
  passed: boolean;
  warnings: string[];
  mean_volume_db?: number | null;
  black_seconds?: number;
}

export interface ClipRender {
  status: "none" | "queued" | "rendering" | "done" | "failed";
  file?: string;
  thumbnail?: string | null;
  srt?: string;
  width?: number;
  height?: number;
  duration?: number;
  size_bytes?: number;
  encoder?: string;
  reframe_mode?: string;
  reframe_note?: string;
  facecam_detected?: FacecamRect | null;
  qc?: QcReport;
  rendered_at?: string;
  error?: string;
  suggestion?: string;
  stale?: boolean;
  hash?: string;
}

export interface Clip {
  id: string;
  start: number;
  end: number;
  category: string;
  total_score: number;
  sub_scores: Record<string, number>;
  transcript_excerpt: string;
  reason: string;
  duration_explanation: string;
  llm_enriched: boolean;
  title: string;
  origin: "auto" | "manual";
  edited: boolean;
  virality: number;
  confidence: "high" | "low";
  caption_overrides: Partial<CaptionSettings> | null;
  reframe_overrides: Partial<ReframeSettings> | null;
  caption_words: CaptionWord[] | null;
  render: ClipRender;
}

export interface ClipsResult {
  project_id: string;
  content_type: string;
  duration_preset: string;
  requested_count: number;
  considered_count: number;
  message: string | null;
  clips: Clip[];
  created_at: string;
}

export interface CaptionWord {
  word: string;
  start: number;
  end: number;
}

export interface Job {
  id: string;
  project_id: string | null;
  kind: "process" | "rerank" | "render";
  queue: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  stage: string | null;
  message: string | null;
  error: string | null;
  suggestion: string | null;
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export const CAPTION_STYLE_INFO: Record<Exclude<CaptionStyleName, "none">, { label: string; font: string; desc: string }> = {
  bold_pop: { label: "Bold Pop", font: "Mukta ExtraBold", desc: "Big words, active word pops" },
  karaoke: { label: "Karaoke", font: "Mukta ExtraBold", desc: "Words light up as spoken" },
  clean: { label: "Clean", font: "Mukta SemiBold", desc: "Simple subtitles" },
  boxed: { label: "Boxed", font: "Mukta Bold", desc: "Text on a dark box" },
  horror: { label: "Horror", font: "Anton", desc: "Tall poster font, red" },
  neon: { label: "Neon", font: "Bebas Neue", desc: "Glowing outline" },
};

export const REFRAME_LABELS: Record<ReframeMode, { label: string; desc: string }> = {
  auto: { label: "Auto", desc: "Detects facecam / speaker / gameplay" },
  split: { label: "Facecam split", desc: "Webcam on top, gameplay below" },
  track: { label: "Follow face", desc: "Crop follows the speaker" },
  fit_blur: { label: "Full frame", desc: "Whole frame over a blurred copy" },
  fill: { label: "Crop", desc: "Fill the frame (fixed position)" },
  original: { label: "Letterbox", desc: "Whole frame with black bars" },
};

export interface Preset {
  id: string;
  name: string;
  content_type: ContentType;
  settings: DeepPartial<ProjectSettings>;
  builtin: boolean;
}
