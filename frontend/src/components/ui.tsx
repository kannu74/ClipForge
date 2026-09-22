import { useEffect, type ReactNode } from "react";
import { cx } from "../lib/format";

export function Button({
  children,
  onClick,
  variant = "secondary",
  size = "md",
  disabled,
  type = "button",
  title,
  className,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  type?: "button" | "submit";
  title?: string;
  className?: string;
}) {
  return (
    <button
      type={type}
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" && "px-2.5 py-1 text-xs",
        size === "md" && "px-3.5 py-2 text-sm",
        size === "lg" && "px-5 py-3 text-base",
        variant === "primary" && "bg-accent text-white hover:bg-accent-hover",
        variant === "secondary" && "border border-surface-border bg-surface-raised text-slate-200 hover:border-slate-500",
        variant === "ghost" && "text-slate-400 hover:bg-surface-raised hover:text-slate-200",
        variant === "danger" && "border border-red-900 bg-red-950/40 text-red-300 hover:bg-red-900/40",
        className
      )}
    >
      {children}
    </button>
  );
}

export function LinkButton({
  href,
  children,
  download,
  variant = "secondary",
  size = "md",
  title,
}: {
  href: string;
  children: ReactNode;
  download?: boolean;
  variant?: "primary" | "secondary";
  size?: "sm" | "md";
  title?: string;
}) {
  return (
    <a
      href={href}
      download={download}
      title={title}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm",
        variant === "primary"
          ? "bg-accent text-white hover:bg-accent-hover"
          : "border border-surface-border bg-surface-raised text-slate-200 hover:border-slate-500"
      )}
    >
      {children}
    </a>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-2xl border border-surface-border bg-surface-raised", className)}>{children}</div>;
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cx("h-4 w-4 animate-spin", className)} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function ProgressBar({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cx("h-2 w-full overflow-hidden rounded-full bg-surface", className)}>
      <div
        className="h-full rounded-full bg-gradient-to-r from-accent to-fuchsia-500 transition-[width] duration-500"
        style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }}
      />
    </div>
  );
}

export function ErrorBox({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-200">
      <span className="mt-0.5">⚠</span>
      <span className="flex-1">{message}</span>
      {onDismiss && (
        <button onClick={onDismiss} className="text-red-400 hover:text-red-200" aria-label="Dismiss">
          ✕
        </button>
      )}
    </div>
  );
}

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  size = "md",
}: {
  value: T;
  options: { value: T; label: ReactNode; title?: string }[];
  onChange: (v: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div className="inline-flex flex-wrap gap-1 rounded-xl border border-surface-border bg-surface p-1">
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          title={o.title}
          onClick={() => onChange(o.value)}
          className={cx(
            "rounded-lg font-medium transition-colors",
            size === "sm" ? "px-2 py-1 text-xs" : "px-3 py-1.5 text-sm",
            value === o.value ? "bg-accent text-white" : "text-slate-400 hover:bg-surface-raised hover:text-slate-200"
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode }) {
  return (
    <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-slate-300">
      <span
        className={cx(
          "relative inline-block h-5 w-9 rounded-full transition-colors",
          checked ? "bg-accent" : "bg-slate-700"
        )}
        onClick={(e) => {
          e.preventDefault();
          onChange(!checked);
        }}
      >
        <span
          className={cx(
            "absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all",
            checked ? "left-[18px]" : "left-0.5"
          )}
        />
      </span>
      <span onClick={() => onChange(!checked)}>{label}</span>
    </label>
  );
}

export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      {children}
      {hint && <div className="text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function Slider({
  value,
  min,
  max,
  step = 1,
  onChange,
  format,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[#7c5cff]"
      />
      <span className="w-12 text-right font-mono text-xs text-slate-300">{format ? format(value) : value}</span>
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className={cx(
          "mt-10 w-full rounded-2xl border border-surface-border bg-surface-raised shadow-2xl",
          wide ? "max-w-5xl" : "max-w-lg"
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-surface-border px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-200" aria-label="Close">
            ✕
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function TimeInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder ?? "m:ss"}
      className="w-24 rounded-lg border border-surface-border bg-surface px-2.5 py-1.5 font-mono text-sm text-slate-100 outline-none focus:border-accent"
    />
  );
}

/** Big, obvious captions on/off switch -- used wherever captions can be set. */
export function CaptionsOnOff({
  enabled,
  onChange,
  compact,
}: {
  enabled: boolean;
  onChange: (v: boolean) => void;
  compact?: boolean;
}) {
  const base = "flex flex-1 items-center justify-center gap-2 rounded-lg font-semibold transition-colors";
  const size = compact ? "px-3 py-1.5 text-xs" : "px-4 py-2.5 text-sm";
  return (
    <div className="flex gap-1 rounded-xl border-2 border-accent/60 bg-accent/5 p-1" role="radiogroup" aria-label="Captions">
      <button
        type="button"
        role="radio"
        aria-checked={enabled}
        onClick={() => onChange(true)}
        className={cx(base, size, enabled ? "bg-accent text-white shadow" : "text-slate-400 hover:bg-surface-raised hover:text-slate-200")}
      >
        <span className="rounded bg-white/20 px-1 font-mono text-[10px]">CC</span> With captions
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={!enabled}
        onClick={() => onChange(false)}
        className={cx(base, size, !enabled ? "bg-slate-600 text-white shadow" : "text-slate-400 hover:bg-surface-raised hover:text-slate-200")}
      >
        No captions
      </button>
    </div>
  );
}
