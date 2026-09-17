import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { HardwareReport } from "../lib/types";

const MODE_LABELS: Record<string, string> = {
  fast: "Fast",
  balanced: "Balanced",
  high_quality: "High Quality",
  maximum_quality: "Maximum Quality",
};

export default function HardwareBadge() {
  const [hw, setHw] = useState<HardwareReport | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    api
      .hardware()
      .then(setHw)
      .catch(() => setError(true));
  }, []);

  if (error) {
    return (
      <div className="flex items-center gap-2 rounded-full border border-red-900 bg-red-950/40 px-3 py-1 text-xs text-red-300">
        <span className="h-2 w-2 rounded-full bg-red-500" />
        Backend unreachable
      </div>
    );
  }

  if (!hw) {
    return (
      <div className="rounded-full border border-surface-border bg-surface-raised px-3 py-1 text-xs text-slate-500">
        Detecting hardware...
      </div>
    );
  }

  const gpuLabel = hw.gpu.available
    ? `${hw.gpu.name ?? "GPU"} · ${Math.round((hw.gpu.vram_total_mb ?? 0) / 1024)}GB VRAM`
    : "CPU only";

  return (
    <div
      className="flex items-center gap-3 rounded-full border border-surface-border bg-surface-raised px-3 py-1.5 text-xs text-slate-300"
      title={`${hw.cpu_cores_logical} logical cores · ${Math.round(hw.ram_total_mb / 1024)}GB RAM · ffmpeg ${
        hw.ffmpeg_available ? "found" : "MISSING"
      } · Ollama ${hw.ollama_reachable ? `reachable (${hw.ollama_models.length} models)` : "not reachable"}`}
    >
      <span className="h-2 w-2 rounded-full bg-emerald-500" />
      <span>{gpuLabel}</span>
      <span className="text-slate-600">·</span>
      <span>{MODE_LABELS[hw.recommended_quality_mode] ?? hw.recommended_quality_mode}</span>
      {!hw.ffmpeg_available && <span className="text-amber-400">· ffmpeg missing</span>}
      {!hw.ollama_reachable && <span className="text-amber-400">· Ollama offline</span>}
    </div>
  );
}
