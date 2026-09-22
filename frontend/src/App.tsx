import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import HardwareBadge from "./components/HardwareBadge";
import { api } from "./lib/api";
import type { Capabilities } from "./lib/types";

export default function App() {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [updatePending, setUpdatePending] = useState(false);
  useEffect(() => {
    api.capabilities().then(setCaps).catch(() => {});
    // ClipForge updated on disk while this server kept running? Then fixes
    // don't apply until a restart -- say so instead of failing mysteriously.
    const check = () => api.health().then((h) => setUpdatePending(!!h.update_pending)).catch(() => {});
    check();
    const t = window.setInterval(check, 30000);
    return () => window.clearInterval(t);
  }, []);

  const problems: string[] = [];
  if (caps) {
    if (!caps.ffmpeg.available) problems.push("FFmpeg wasn't found — videos can't be processed. Re-run ClipForge setup.");
    else if (!caps.ffmpeg.captions_supported)
      problems.push("Your FFmpeg build can't burn in captions. Re-run ClipForge setup to use the bundled FFmpeg.");
    if (caps.gpu_transcription?.nvidia_gpu && !caps.gpu_transcription.cuda_libs_installed)
      problems.push(
        "Your NVIDIA GPU isn't used for transcription yet (slower and less accurate on CPU). Close ClipForge and start ClipForge.bat again — it installs GPU support automatically."
      );
    if (!caps.face_detection) problems.push("Face detection isn't available, so smart framing falls back to full-frame.");
  }

  return (
    <div className="min-h-screen bg-surface">
      <header className="sticky top-0 z-40 border-b border-surface-border bg-surface/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
          <Link to="/" className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-fuchsia-500 text-sm font-black text-white">
              C
            </div>
            <span className="text-base font-semibold tracking-wide text-slate-100">ClipForge</span>
          </Link>
          <HardwareBadge />
        </div>
      </header>
      {updatePending && (
        <div className="border-b border-accent/60 bg-accent/15 px-6 py-2.5 text-center text-sm font-medium text-slate-100">
          ClipForge has been updated. Close the black ClipForge window and start ClipForge.bat again to use the new version —
          until then the old version keeps running.
        </div>
      )}
      {problems.length > 0 && (
        <div className="border-b border-amber-900 bg-amber-950/40 px-6 py-2 text-center text-xs text-amber-200">{problems.join(" ")}</div>
      )}
      <main className="mx-auto max-w-7xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
