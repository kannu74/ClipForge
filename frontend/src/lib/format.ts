export function fmtTime(seconds: number | null | undefined, withTenths = false): string {
  if (seconds == null || !isFinite(seconds)) return "--:--";
  const neg = seconds < 0;
  let s = Math.abs(seconds);
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  s -= m * 60;
  const sec = withTenths ? s.toFixed(1).padStart(4, "0") : String(Math.floor(s)).padStart(2, "0");
  const body = h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
  return neg ? `-${body}` : body;
}

/** Parse "1:23", "01:02:03", "83", "83.5" into seconds. Returns null if invalid. */
export function parseTime(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  const parts = t.split(":").map((p) => p.trim());
  if (parts.some((p) => p === "" || isNaN(Number(p)))) return null;
  let total = 0;
  for (const p of parts) total = total * 60 + Number(p);
  return total >= 0 ? total : null;
}

export function fmtBytes(n: number | null | undefined): string {
  if (!n) return "";
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function fmtDuration(seconds: number): string {
  return seconds >= 60 ? fmtTime(seconds) : `${Math.round(seconds)}s`;
}

export function timeAgo(iso: string): string {
  const d = new Date(iso).getTime();
  const diff = (Date.now() - d) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export function isYoutubeUrl(text: string): boolean {
  return /^(https?:\/\/)?((www|m|music)\.)?(youtube\.com\/(watch|shorts|live|embed)|youtu\.be\/)/i.test(text.trim());
}

export function viralityColor(v: number): string {
  const base = "bg-black/80 ";
  if (v >= 80) return base + "text-emerald-300 border-emerald-400/60";
  if (v >= 60) return base + "text-lime-300 border-lime-400/60";
  if (v >= 40) return base + "text-amber-300 border-amber-400/60";
  return base + "text-slate-300 border-slate-400/50";
}

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}
