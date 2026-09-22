import { useRef, useState, type PointerEvent } from "react";
import { fmtTime } from "../lib/format";

/**
 * Timeline around a clip: drag the handles to trim, click to seek. Shows
 * the clip region in context (±30s) so extending into setup/aftermath is easy.
 */
export default function TrimTimeline({
  duration,
  start,
  end,
  current,
  onChange,
  onSeek,
  context = 30,
  marks = [],
}: {
  duration: number;
  start: number;
  end: number;
  current: number;
  onChange: (start: number, end: number) => void;
  onSeek: (t: number) => void;
  context?: number;
  marks?: { t: number; label: string }[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<"start" | "end" | null>(null);
  // Freeze the visible window while dragging so the handle doesn't run away.
  const [frozen, setFrozen] = useState<[number, number] | null>(null);
  const viewStart = frozen ? frozen[0] : Math.max(0, start - context);
  const viewEnd = frozen ? frozen[1] : Math.min(duration || end + context, end + context);
  const span = Math.max(viewEnd - viewStart, 1);

  const pct = (t: number) => `${((t - viewStart) / span) * 100}%`;
  const timeAt = (clientX: number) => {
    const b = ref.current!.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (clientX - b.left) / b.width));
    return viewStart + f * span;
  };

  function onPointerMove(e: PointerEvent) {
    if (!drag) return;
    const t = Math.round(timeAt(e.clientX) * 10) / 10;
    if (drag === "start") onChange(Math.min(t, end - 1), end);
    else onChange(start, Math.max(t, start + 1));
  }

  const ticks: number[] = [];
  const step = span > 1800 ? 300 : span > 600 ? 60 : span > 240 ? 30 : span > 90 ? 15 : span > 25 ? 5 : 2;
  for (let t = Math.ceil(viewStart / step) * step; t <= viewEnd - span * 0.04; t += step) ticks.push(t);

  return (
    <div className="select-none">
      <div
        ref={ref}
        className="relative h-14 cursor-pointer rounded-lg bg-surface"
        onPointerMove={onPointerMove}
        onPointerUp={() => {
          setDrag(null);
          setFrozen(null);
        }}
        onPointerDown={(e) => {
          if ((e.target as HTMLElement).dataset.handle) return;
          onSeek(timeAt(e.clientX));
        }}
      >
        {ticks.map((t) => (
          <div key={t} className="absolute top-0 h-2 border-l border-slate-600" style={{ left: pct(t) }}>
            <span className="absolute left-1 top-1.5 font-mono text-[9px] text-slate-600">{fmtTime(t)}</span>
          </div>
        ))}
        {marks.map((m, i) => (
          <div key={i} className="absolute bottom-0 h-3 border-l border-fuchsia-400/70" style={{ left: pct(m.t) }} title={m.label} />
        ))}
        <div
          className="absolute bottom-0 top-4 rounded-md border-2 border-accent bg-accent/25"
          style={{ left: pct(start), width: `${((end - start) / span) * 100}%` }}
        />
        {(["start", "end"] as const).map((h) => (
          <div
            key={h}
            data-handle={h}
            onPointerDown={(e) => {
              e.stopPropagation();
              (e.target as HTMLElement).setPointerCapture(e.pointerId);
              setFrozen([viewStart, viewEnd]);
              setDrag(h);
            }}
            className="absolute bottom-0 top-3 z-10 w-3 -translate-x-1/2 cursor-ew-resize rounded bg-white shadow"
            style={{ left: pct(h === "start" ? start : end) }}
            title={h === "start" ? "Drag to change the start" : "Drag to change the end"}
          />
        ))}
        <div className="pointer-events-none absolute bottom-0 top-0 z-20 w-0.5 bg-red-500" style={{ left: pct(Math.min(Math.max(current, viewStart), viewEnd)) }} />
      </div>
      <div className="mt-1 flex justify-between font-mono text-[11px] text-slate-500">
        <span>{fmtTime(viewStart)}</span>
        <span className="text-slate-300">
          {fmtTime(start, true)} → {fmtTime(end, true)} ({(end - start).toFixed(1)}s)
        </span>
        <span>{fmtTime(viewEnd)}</span>
      </div>
    </div>
  );
}
