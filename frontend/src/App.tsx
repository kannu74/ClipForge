import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import HardwareBadge from "./components/HardwareBadge";
import { api } from "./lib/api";
import type { Capabilities } from "./lib/types";

export default function App() {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  useEffect(() => {
    api.capabilities().then(setCaps).catch(() => {});
  }, []);

  const problems: string[] = [];
  if (caps) {
    if (!caps.ffmpeg.available) problems.push("FFmpeg wasn't found — videos can't be processed. Re-run ClipForge setup.");
    else if (!caps.ffmpeg.captions_supported)
      problems.push("Your FFmpeg build can't burn in captions. Re-run ClipForge setup to use the bundled FFmpeg.");
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
      {problems.length > 0 && (
        <div className="border-b border-amber-900 bg-amber-950/40 px-6 py-2 text-center text-xs text-amber-200">{problems.join(" ")}</div>
      )}
      <main className="mx-auto max-w-7xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
