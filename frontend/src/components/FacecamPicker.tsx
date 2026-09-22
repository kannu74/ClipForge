import { useRef, useState, type PointerEvent } from "react";
import { api } from "../lib/api";
import { fmtTime } from "../lib/format";
import type { FacecamRect } from "../lib/types";
import { Button, Modal, Slider } from "./ui";

/** Draw a rectangle over a frame of the source video to mark the facecam. */
export default function FacecamPicker({
  open,
  onClose,
  projectId,
  time,
  duration,
  initial,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  time: number;
  duration: number;
  initial: FacecamRect | null;
  onSave: (rect: FacecamRect) => void;
}) {
  const [t, setT] = useState(time);
  const [rect, setRect] = useState<FacecamRect | null>(initial);
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  function pos(e: PointerEvent) {
    const b = boxRef.current!.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (e.clientX - b.left) / b.width)),
      y: Math.min(1, Math.max(0, (e.clientY - b.top) / b.height)),
    };
  }

  return (
    <Modal open={open} onClose={onClose} title="Mark the facecam" wide>
      <p className="mb-3 text-sm text-slate-400">
        Drag a box around the webcam overlay. It becomes the top panel of the split layout; the rest of the frame is the gameplay panel.
      </p>
      <div
        ref={boxRef}
        className="relative w-full cursor-crosshair select-none overflow-hidden rounded-xl border border-surface-border"
        onPointerDown={(e) => {
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
          const p = pos(e);
          setDrag(p);
          setRect({ x: p.x, y: p.y, w: 0.001, h: 0.001 });
        }}
        onPointerMove={(e) => {
          if (!drag) return;
          const p = pos(e);
          setRect({
            x: Math.min(drag.x, p.x),
            y: Math.min(drag.y, p.y),
            w: Math.max(0.001, Math.abs(p.x - drag.x)),
            h: Math.max(0.001, Math.abs(p.y - drag.y)),
          });
        }}
        onPointerUp={() => setDrag(null)}
      >
        <img src={api.frameUrl(projectId, t, 960)} alt="Source frame" className="pointer-events-none block w-full" draggable={false} />
        {rect && (
          <div
            className="pointer-events-none absolute border-2 border-accent bg-accent/20"
            style={{ left: `${rect.x * 100}%`, top: `${rect.y * 100}%`, width: `${rect.w * 100}%`, height: `${rect.h * 100}%` }}
          />
        )}
      </div>
      <div className="mt-3">
        <div className="mb-1 text-xs text-slate-500">Frame at {fmtTime(t)}</div>
        <Slider value={t} min={0} max={Math.max(1, duration)} step={0.5} onChange={setT} format={(v) => fmtTime(v)} />
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="primary"
          disabled={!rect || rect.w < 0.03 || rect.h < 0.03}
          onClick={() => {
            if (rect) onSave(rect);
            onClose();
          }}
        >
          Use this area
        </Button>
      </div>
    </Modal>
  );
}
