import { Link, Outlet } from "react-router-dom";
import HardwareBadge from "./components/HardwareBadge";

export default function App() {
  return (
    <div className="min-h-screen bg-surface">
      <header className="sticky top-0 z-40 border-b border-surface-border bg-surface/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <Link to="/" className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-sm font-bold text-white">
              C
            </div>
            <span className="text-sm font-semibold tracking-wide text-slate-100">ClipForge</span>
          </Link>
          <HardwareBadge />
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
