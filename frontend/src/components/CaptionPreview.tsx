import { useEffect, useState, type CSSProperties } from "react";
import { CAPTION_STYLE_INFO, type CaptionSettings } from "../lib/types";

const POSITION_Y: Record<string, number> = { top: 0.16, upper: 0.3, middle: 0.5, lower: 0.7, bottom: 0.8 };
const SIZE_RATIO: Record<string, number> = {
  bold_pop: 0.064,
  karaoke: 0.06,
  clean: 0.042,
  boxed: 0.052,
  horror: 0.068,
  neon: 0.08,
};
const EMPHASIS = new Set(["insane", "crazy", "omg", "clutch", "scary", "bhoot", "wtf", "noob", "paagal", "headshot", "wow"]);

/**
 * CSS approximation of the burned-in caption styles (same fonts, colours,
 * proportions and word-highlight behaviour as the ASS renderer), so style
 * choices can be judged instantly without waiting for a render.
 */
export default function CaptionPreview({
  cfg,
  sample = "bhai WAIT no way this is insane",
  height = 360,
  background,
  aspect = 9 / 16,
  animate = true,
  captionY,
  fixedFontPx,
  fill,
  title,
}: {
  cfg: CaptionSettings;
  sample?: string;
  height?: number;
  background?: string;
  aspect?: number;
  animate?: boolean;
  captionY?: number;
  fixedFontPx?: number;
  fill?: boolean;
  title?: string;
}) {
  const words = sample.split(/\s+/).filter(Boolean);
  const per = Math.max(1, cfg.words_per_line * cfg.max_lines);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!animate) return;
    const id = setInterval(() => setTick((t) => t + 1), 450);
    return () => clearInterval(id);
  }, [animate]);

  const lineCount = Math.ceil(words.length / per);
  const idx = tick % words.length;
  const lineIdx = Math.floor(idx / per) % lineCount;
  const lineWords = words.slice(lineIdx * per, lineIdx * per + per);
  const active = idx - lineIdx * per;

  const width = height * aspect;
  const style = cfg.style === "none" ? "bold_pop" : cfg.style;
  const info = CAPTION_STYLE_INFO[style];
  const font = cfg.font || info.font;
  const fontPx = fixedFontPx ?? (SIZE_RATIO[style] ?? 0.06) * height * cfg.font_scale;
  const highlight =
    style === "horror" && cfg.highlight_color.toUpperCase() === "#FFE14D" ? "#FF2A2A" : cfg.highlight_color;
  const y = captionY ?? POSITION_Y[cfg.position] ?? 0.7;

  const base: CSSProperties = {
    fontFamily: `"${font}", "Mukta ExtraBold", sans-serif`,
    fontSize: fontPx,
    lineHeight: 1.15,
    color: cfg.text_color,
    letterSpacing: style === "neon" ? fontPx * 0.02 : undefined,
  };
  if (style === "boxed") {
    Object.assign(base, { background: "#101010", padding: `${fontPx * 0.1}px ${fontPx * 0.3}px`, borderRadius: 4 });
  } else if (style === "neon") {
    Object.assign(base, { WebkitTextStroke: `${fontPx * 0.05}px #29F0FF`, textShadow: `0 0 ${fontPx * 0.25}px #29F0FF` });
  } else {
    const ratio = style === "clean" ? 0.08 : style === "horror" ? 0.08 : 0.1;
    Object.assign(base, {
      WebkitTextStroke: `${fontPx * ratio * 2}px ${cfg.outline_color}`,
      textShadow: `0 ${fontPx * 0.04}px ${fontPx * 0.06}px rgba(0,0,0,0.6)`,
    });
  }

  return (
    <div
      className="relative overflow-hidden rounded-xl bg-gradient-to-b from-slate-700 to-slate-900"
      style={{ width: fill ? "100%" : width, height, backgroundImage: background ? `url(${background})` : undefined, backgroundSize: "cover", backgroundPosition: "center" }}
    >
      {title && (
        <div className="absolute left-1/2 top-[6%] w-[84%] -translate-x-1/2 text-center">
          <span
            style={{
              fontFamily: '"Mukta ExtraBold", sans-serif',
              fontSize: height * 0.036,
              lineHeight: 1.35,
              background: "#fff",
              color: "#111",
              padding: `${height * 0.006}px ${height * 0.012}px`,
              boxDecorationBreak: "clone",
              WebkitBoxDecorationBreak: "clone",
            }}
          >
            {title}
          </span>
        </div>
      )}
      {cfg.enabled && cfg.style !== "none" && (
        <div
          className="absolute left-1/2 w-[92%] -translate-x-1/2 -translate-y-1/2 text-center"
          style={{ top: `${y * 100}%` }}
        >
          <span className="caption-stroke" style={base}>
            {lineWords.map((w, i) => {
              const txt = cfg.uppercase ? w.toUpperCase() : w;
              const isActive = style !== "clean" && i === active;
              const spoken = style === "karaoke" && i < active;
              const emph = cfg.emphasize_keywords && EMPHASIS.has(w.toLowerCase());
              const color = isActive || spoken ? highlight : emph ? "#3CFF7A" : undefined;
              return (
                <span key={`${lineIdx}-${i}-${isActive ? tick : 0}`}>
                  <span className={isActive && (style === "bold_pop" || style === "horror") ? "cf-pop" : undefined} style={{ color }}>
                    {txt}
                  </span>
                  {i < lineWords.length - 1 ? " " : ""}
                </span>
              );
            })}
          </span>
        </div>
      )}
    </div>
  );
}
