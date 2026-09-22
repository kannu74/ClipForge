import {
  CAPTION_STYLE_INFO,
  DURATION_PRESET_LABELS,
  REFRAME_LABELS,
  type AspectRatio,
  type CaptionSettings,
  type CaptionStyleName,
  type DurationPreset,
  type ProjectSettings,
  type ReframeMode,
  type ReframeSettings,
} from "../lib/types";
import { cx } from "../lib/format";
import CaptionPreview from "./CaptionPreview";
import { CaptionsOnOff, Field, Segmented, Slider, Toggle } from "./ui";

export function ClipOptions({
  value,
  onChange,
  compact,
}: {
  value: ProjectSettings;
  onChange: (patch: Partial<ProjectSettings>) => void;
  compact?: boolean;
}) {
  return (
    <div className={cx("grid gap-5", compact ? "grid-cols-1" : "md:grid-cols-2")}>
      <Field label="Clip length">
        <Segmented<DurationPreset>
          size="sm"
          value={value.duration_preset}
          onChange={(v) => onChange({ duration_preset: v })}
          options={(Object.keys(DURATION_PRESET_LABELS) as DurationPreset[]).map((k) => ({
            value: k,
            label: DURATION_PRESET_LABELS[k],
          }))}
        />
        {value.duration_preset === "custom" && (
          <div className="mt-2 flex items-center gap-2 text-sm text-slate-400">
            <input
              type="number"
              min={3}
              max={180}
              value={value.custom_min_seconds ?? 15}
              onChange={(e) => onChange({ custom_min_seconds: Number(e.target.value) })}
              className="w-20 rounded-lg border border-surface-border bg-surface px-2 py-1 text-slate-100"
            />
            to
            <input
              type="number"
              min={5}
              max={180}
              value={value.custom_max_seconds ?? 45}
              onChange={(e) => onChange({ custom_max_seconds: Number(e.target.value) })}
              className="w-20 rounded-lg border border-surface-border bg-surface px-2 py-1 text-slate-100"
            />
            seconds
          </div>
        )}
      </Field>
      <Field label={`Number of clips: ${value.clip_count}`} hint="ClipForge returns fewer if there aren't that many good moments.">
        <Slider value={value.clip_count} min={1} max={20} onChange={(v) => onChange({ clip_count: v })} />
      </Field>
      <Field label="Spoken language" hint="Auto-detect works best for Hinglish (mixed Hindi + English).">
        <Segmented<string>
          size="sm"
          value={value.language}
          onChange={(v) => onChange({ language: v })}
          options={[
            { value: "", label: "Auto" },
            { value: "hi", label: "Hindi" },
            { value: "en", label: "English" },
          ]}
        />
      </Field>
      <Field label="Transcription accuracy" hint="Bigger = more accurate but slower. Auto picks for your hardware.">
        <Segmented<string>
          size="sm"
          value={value.whisper_model ?? "auto"}
          onChange={(v) => onChange({ whisper_model: v === "auto" ? null : v })}
          options={[
            { value: "auto", label: "Auto" },
            { value: "small", label: "Fast" },
            { value: "medium", label: "Better" },
            { value: "large-v3-turbo", label: "Best (GPU)" },
          ]}
        />
      </Field>
      <div className="flex flex-col gap-2 md:col-span-2">
        <Toggle
          checked={value.auto_render}
          onChange={(v) => onChange({ auto_render: v })}
          label="Render videos automatically (with captions and framing)"
        />
        <Toggle
          checked={value.include_backup_clips}
          onChange={(v) => onChange({ include_backup_clips: v })}
          label="Fill up with clearly-labelled backup clips if there aren't enough strong moments"
        />
      </div>
    </div>
  );
}

export function CaptionControls({
  value,
  onChange,
  showPreview = true,
  narrow,
}: {
  value: CaptionSettings;
  onChange: (patch: Partial<CaptionSettings>) => void;
  showPreview?: boolean;
  narrow?: boolean;
}) {
  const styles = Object.keys(CAPTION_STYLE_INFO) as Exclude<CaptionStyleName, "none">[];
  return (
    <div className="space-y-5">
      <Field label="Captions" hint={value.enabled ? "Captions are burned into the video. An .srt file is always included too." : "No captions will be burned in (an .srt file is still included)."}>
        <CaptionsOnOff enabled={value.enabled} onChange={(v) => onChange({ enabled: v })} />
      </Field>
      <div className={cx("space-y-5", !value.enabled && "pointer-events-none opacity-40")}>
        <Field label="Style">
          <div className="grid grid-cols-3 gap-2">
            {styles.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onChange({ style: s, uppercase: s === "clean" ? false : value.uppercase || value.style === "clean" })}
                className={cx(
                  "overflow-hidden rounded-xl border p-1 text-left transition-colors",
                  value.style === s ? "border-accent ring-1 ring-accent" : "border-surface-border hover:border-slate-500"
                )}
              >
                <CaptionPreview
                  cfg={{ ...value, style: s, uppercase: s === "clean" ? false : true, position: "middle", enabled: true }}
                  sample="no way bro"
                  height={64}
                  fill
                  fixedFontPx={s === "neon" ? 24 : s === "clean" ? 17 : 20}
                  animate={value.style === s}
                />
                <div className="px-1 pt-1 text-xs font-medium text-slate-200">{CAPTION_STYLE_INFO[s].label}</div>
              </button>
            ))}
          </div>
        </Field>
        <div className={cx("grid gap-5", narrow ? "grid-cols-1" : "md:grid-cols-2")}>
          <Field label="Position">
            <Segmented
              size="sm"
              value={value.position}
              onChange={(v) => onChange({ position: v })}
              options={[
                { value: "top", label: "Top" },
                { value: "upper", label: "Upper" },
                { value: "middle", label: "Middle" },
                { value: "lower", label: "Lower" },
                { value: "bottom", label: "Bottom" },
              ]}
            />
          </Field>
          <Field label="Script" hint="Roman turns Devanagari into Hinglish (bhai ye kya hai). Words are never translated.">
            <Segmented
              size="sm"
              value={value.script}
              onChange={(v) => onChange({ script: v })}
              options={[
                { value: "as_spoken", label: "As transcribed" },
                { value: "roman", label: "Roman Hinglish" },
              ]}
            />
          </Field>
          <Field label="Size">
            <Slider value={value.font_scale} min={0.6} max={1.6} step={0.05} onChange={(v) => onChange({ font_scale: v })} format={(v) => `${Math.round(v * 100)}%`} />
          </Field>
          <Field label="Words per line">
            <Slider value={value.words_per_line} min={1} max={6} onChange={(v) => onChange({ words_per_line: v })} />
          </Field>
          <Field label="Colours">
            <div className="flex items-center gap-4 text-xs text-slate-400">
              {(
                [
                  ["text_color", "Text"],
                  ["highlight_color", "Highlight"],
                  ["outline_color", "Outline"],
                ] as const
              ).map(([k, label]) => (
                <label key={k} className="flex items-center gap-1.5">
                  <input
                    type="color"
                    value={value[k]}
                    onChange={(e) => onChange({ [k]: e.target.value.toUpperCase() } as Partial<CaptionSettings>)}
                    className="h-7 w-9 cursor-pointer rounded border border-surface-border bg-transparent"
                  />
                  {label}
                </label>
              ))}
            </div>
          </Field>
          <div className="flex flex-col justify-end gap-2">
            <Toggle checked={value.uppercase} onChange={(v) => onChange({ uppercase: v })} label="UPPERCASE" />
            <Toggle checked={value.emphasize_keywords} onChange={(v) => onChange({ emphasize_keywords: v })} label="Colour hype words (insane, clutch, bhoot...)" />
          </div>
        </div>
        <Field label="Hook title">
          <div className="flex flex-wrap items-center gap-3">
            <Toggle
              checked={value.title_overlay}
              onChange={(v) => onChange({ title_overlay: v })}
              label="Show the clip's title at the top"
            />
            {value.title_overlay && (
              <Segmented<number>
                size="sm"
                value={value.title_seconds}
                onChange={(v) => onChange({ title_seconds: v })}
                options={[
                  { value: 3, label: "First 3s" },
                  { value: 5, label: "First 5s" },
                  { value: 0, label: "Whole clip" },
                ]}
              />
            )}
          </div>
        </Field>
        {showPreview && (
          <div className="flex justify-center">
            <CaptionPreview cfg={value} height={300} title={value.title_overlay ? "Bhai ye kya ho gaya?!" : undefined} />
          </div>
        )}
      </div>
    </div>
  );
}

export function FramingControls({
  value,
  onChange,
  onPickFacecam,
  narrow,
}: {
  value: ReframeSettings;
  onChange: (patch: Partial<ReframeSettings>) => void;
  onPickFacecam?: () => void;
  narrow?: boolean;
}) {
  const modes = Object.keys(REFRAME_LABELS) as ReframeMode[];
  return (
    <div className="space-y-5">
      <Field label="Shape">
        <Segmented<AspectRatio>
          size="sm"
          value={value.aspect}
          onChange={(v) => onChange({ aspect: v })}
          options={[
            { value: "9:16", label: "9:16 Shorts/Reels" },
            { value: "1:1", label: "1:1" },
            { value: "4:5", label: "4:5" },
            { value: "16:9", label: "16:9" },
          ]}
        />
      </Field>
      <Field label="Framing">
        <div className={cx("grid grid-cols-2 gap-2", !narrow && "md:grid-cols-3")}>
          {modes.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => onChange({ mode: m })}
              className={cx(
                "rounded-xl border px-3 py-2 text-left transition-colors",
                value.mode === m ? "border-accent bg-accent/10" : "border-surface-border hover:border-slate-500"
              )}
            >
              <div className="text-sm font-medium text-slate-100">{REFRAME_LABELS[m].label}</div>
              <div className="text-xs text-slate-500">{REFRAME_LABELS[m].desc}</div>
            </button>
          ))}
        </div>
      </Field>
      {(value.mode === "split" || value.mode === "auto") && value.aspect !== "16:9" && value.aspect !== "1:1" && (
        <div className={cx("grid gap-5", narrow ? "grid-cols-1" : "md:grid-cols-2")}>
          <Field label="Facecam area" hint={value.facecam ? "Using the area you marked." : "Detected automatically — mark it yourself if it's wrong."}>
            <div className="flex gap-2">
              {onPickFacecam && (
                <button
                  type="button"
                  onClick={onPickFacecam}
                  className="rounded-lg border border-surface-border px-3 py-1.5 text-sm text-slate-200 hover:border-slate-500"
                >
                  {value.facecam ? "Adjust facecam area" : "Mark facecam area"}
                </button>
              )}
              {value.facecam && (
                <button type="button" onClick={() => onChange({ facecam: null })} className="text-xs text-slate-400 hover:text-slate-200">
                  Use auto-detect
                </button>
              )}
            </div>
          </Field>
          <Field label={`Facecam panel height: ${Math.round(value.split_ratio * 100)}%`}>
            <Slider value={value.split_ratio} min={0.25} max={0.55} step={0.01} onChange={(v) => onChange({ split_ratio: v })} format={(v) => `${Math.round(v * 100)}%`} />
            <Toggle checked={value.facecam_on_top} onChange={(v) => onChange({ facecam_on_top: v })} label="Facecam on top" />
          </Field>
        </div>
      )}
      {(value.mode === "fill" || value.mode === "split") && (
        <Field label="Horizontal focus" hint="Which part of the gameplay to keep when cropping.">
          <Slider value={value.focus_x} min={0} max={1} step={0.01} onChange={(v) => onChange({ focus_x: v })} format={(v) => (v < 0.4 ? "Left" : v > 0.6 ? "Right" : "Center")} />
        </Field>
      )}
    </div>
  );
}
