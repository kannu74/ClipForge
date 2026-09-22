"""
Phase 6 -- captions.

Turns the words spoken inside a clip into burned-in, word-synced captions
(ASS subtitles rendered by ffmpeg/libass) plus a plain SRT for uploading
separately. Quality rules this module enforces:

  * Hinglish stays Hinglish. Text is shown exactly as transcribed (or as the
    creator edited it). The only optional change is script: Devanagari can be
    transliterated to Roman ("bhai ye kya hai") -- never translated.
  * Lines break where speech breaks: at sentence punctuation, at pauses, and
    at a word budget -- never mid-phrase just because a character count hit.
  * A line never runs off the frame: the word budget is derived from the
    output width and font size, and an unavoidable over-long line is scaled
    down rather than clipped.
  * Devanagari always renders: if a caption line contains Devanagari and the
    style's display font lacks it, a Devanagari-capable font is used instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.project_settings import CaptionSettings
from app.translit import has_devanagari, to_roman

FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"


def fonts_dir_for_render(render_dir: Path) -> str:
    """Path to the caption fonts, relative to the render working directory.

    ffmpeg filter arguments can't safely hold arbitrary absolute paths
    (Windows drive colons, apostrophes in user names like D'Souza...), so the
    fonts are mirrored into the data folder -- always on the same drive as
    the renders -- and referenced with a plain relative path like ../../../fonts."""
    import os
    import shutil

    from app.config import settings

    target = (settings.data_dir / "fonts").resolve()
    target.mkdir(parents=True, exist_ok=True)
    for f in FONTS_DIR.glob("*.ttf"):
        dst = target / f.name
        if not dst.exists() or dst.stat().st_size != f.stat().st_size:
            shutil.copy2(f, dst)
    rel = os.path.relpath(target, render_dir.resolve())
    return rel.replace("\\", "/")

# Words worth colouring on their own (reaction / hype vocabulary, English +
# Hinglish). Matched case-insensitively on the bare word.
# Deliberately short: if every other word is coloured, nothing stands out.
# Everyday Hinglish ("bhai", "yaar", "kya") is NOT here for that reason.
EMPHASIS_WORDS = {
    "insane", "crazy", "omg", "clutch", "scary", "bhoot", "seriously", "wtf", "legendary",
    "noob", "pagal", "paagal", "zabardast", "khatarnak", "khatarnaak", "headshot",
    "killed", "died", "rip", "wow", "unbelievable", "impossible", "ghost", "jumpscare",
}

SENTENCE_END_RE = re.compile(r"[.?!।॥]+[\"')\]]*$")


@dataclass
class StylePreset:
    font: str                 # display font (Latin)
    deva_font: str            # used when the line contains Devanagari
    size_ratio: float         # font size as a fraction of output height
    bold: bool
    outline_ratio: float      # outline thickness as a fraction of font size
    shadow: float
    blur: float
    box: bool = False         # opaque box behind text (BorderStyle 3)
    box_color: str = "#000000"
    box_alpha: int = 0x40     # 00 = opaque, FF = transparent
    highlight: str = "color"  # color | karaoke | none
    pop: bool = False
    glow: bool = False
    shake: bool = False
    default_uppercase: bool = True
    spacing: float = 0.0


STYLES: dict[str, StylePreset] = {
    # Opus-style: huge bold words, thick outline, active word pops in colour.
    "bold_pop": StylePreset("Mukta ExtraBold", "Mukta ExtraBold", 0.064, False, 0.10, 3.0, 0.6, pop=True),
    # Words fill with colour as they're spoken; already-spoken words stay lit.
    "karaoke": StylePreset("Mukta ExtraBold", "Mukta ExtraBold", 0.060, False, 0.10, 2.5, 0.5, highlight="karaoke"),
    # Understated sentence-case subtitles.
    "clean": StylePreset("Mukta SemiBold", "Mukta SemiBold", 0.042, False, 0.08, 2.0, 0.4,
                         highlight="none", default_uppercase=False),
    # White text on a dark box, active word coloured.
    "boxed": StylePreset("Mukta Bold", "Mukta Bold", 0.052, False, 0.16, 0.0, 0.0, box=True,
                         box_color="#101010", box_alpha=0x00),
    # Condensed poster font, blood-red highlight, slight jitter on the active word.
    "horror": StylePreset("Anton", "Mukta ExtraBold", 0.068, False, 0.08, 3.5, 1.0, pop=True, shake=True),
    # Thin coloured halo around white words.
    "neon": StylePreset("Bebas Neue", "Mukta ExtraBold", 0.080, False, 0.05, 0.0, 2.5, glow=True, spacing=1.0),
}

STYLE_HIGHLIGHT_DEFAULTS = {"horror": "#FF2A2A"}
NEON_GLOW = "#29F0FF"

# Vertical anchor (fraction of output height) for each position.
POSITION_Y = {"top": 0.16, "upper": 0.30, "middle": 0.50, "lower": 0.70, "bottom": 0.80}

# Approximate advance width of an average glyph, as a fraction of font size,
# per font (uppercase-ish text). Used only to keep lines inside the frame.
CHAR_WIDTH = {"Mukta ExtraBold": 0.58, "Mukta Bold": 0.56, "Mukta SemiBold": 0.52,
              "Anton": 0.50, "Bebas Neue": 0.42, "Hind Bold": 0.56}


@dataclass
class CapWord:
    text: str
    start: float
    end: float
    emphasis: bool = False


@dataclass
class CapLine:
    words: list[CapWord] = field(default_factory=list)

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def _get(w, key: str):
    return w.get(key) if isinstance(w, dict) else getattr(w, key)


def prepare_words(words: list, clip_start: float, clip_end: float, cfg: CaptionSettings) -> list[CapWord]:
    """Absolute-time words -> clip-relative caption words (script and case
    applied, emphasis flagged, timing made monotonic and gap-safe)."""
    out: list[CapWord] = []
    for w in words:
        text = str(_get(w, "word") or "").strip()
        if not text:
            continue
        ws = float(_get(w, "start"))
        we = float(_get(w, "end"))
        if we < clip_start or ws > clip_end:
            continue
        if cfg.script == "roman":
            text = to_roman(text)
        bare = re.sub(r"[^\w']", "", to_roman(text).lower())
        out.append(
            CapWord(
                text=text,
                start=max(ws, clip_start) - clip_start,
                end=min(we, clip_end) - clip_start,
                emphasis=cfg.emphasize_keywords and bare in EMPHASIS_WORDS,
            )
        )
    # Monotonic, non-zero durations (Whisper occasionally overlaps words).
    for i, w in enumerate(out):
        if i > 0 and w.start < out[i - 1].end:
            w.start = out[i - 1].end
        if w.end <= w.start:
            w.end = w.start + 0.08
    return out


def _max_chars(cfg: CaptionSettings, preset: StylePreset, width: int, height: int, deva: bool) -> int:
    font = preset.deva_font if deva else (cfg.font or preset.font)
    fs = preset.size_ratio * height * cfg.font_scale
    cw = CHAR_WIDTH.get(font, 0.55) * fs
    return max(6, int((width * 0.86) / cw))


def group_lines(words: list[CapWord], cfg: CaptionSettings, width: int, height: int) -> list[CapLine]:
    preset = STYLES.get(cfg.style, STYLES["bold_pop"])
    lines: list[CapLine] = []
    cur = CapLine()
    budget_words = cfg.words_per_line * cfg.max_lines
    for i, w in enumerate(words):
        if cur.words:
            prospective = cur.text + " " + w.text
            gap = w.start - cur.words[-1].end
            too_long = len(prospective) > _max_chars(cfg, preset, width, height, has_devanagari(prospective)) * cfg.max_lines
            if len(cur.words) >= budget_words or gap > 0.55 or too_long:
                lines.append(cur)
                cur = CapLine()
        cur.words.append(w)
        if SENTENCE_END_RE.search(w.text) and len(cur.words) >= 1:
            lines.append(cur)
            cur = CapLine()
    if cur.words:
        lines.append(cur)

    # Merge a dangling single word into the previous line when they're close
    # and it still fits -- a lone "hai." flashing by is hard to read.
    merged: list[CapLine] = []
    for line in lines:
        if (
            merged
            and len(line.words) == 1
            and len(merged[-1].words) < budget_words + 1
            and line.start - merged[-1].end < 0.3
            and len(merged[-1].text + " " + line.text)
            <= _max_chars(cfg, preset, width, height, has_devanagari(merged[-1].text + line.text)) * cfg.max_lines
            and not SENTENCE_END_RE.search(merged[-1].words[-1].text)
        ):
            merged[-1].words.extend(line.words)
        else:
            merged.append(line)
    return merged


# --- ASS output ---

def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ass_inline_color(hex_rgb: str) -> str:
    h = hex_rgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _ass_time(t: float) -> str:
    t = max(t, 0.0)
    cs = int(round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _display(text: str, cfg: CaptionSettings, preset: StylePreset) -> str:
    return text.upper() if cfg.uppercase else text


def _split_rows(words: list[CapWord], n_rows: int) -> list[list[int]]:
    """Split word indices of one caption line into up to n_rows balanced rows."""
    idx = list(range(len(words)))
    if n_rows <= 1 or len(words) <= 2:
        return [idx]
    per = -(-len(words) // n_rows)
    return [idx[i : i + per] for i in range(0, len(idx), per)]


def build_ass(
    lines: list[CapLine],
    cfg: CaptionSettings,
    width: int,
    height: int,
    clip_duration: float,
    y_override: float | None = None,
) -> str:
    preset = STYLES.get(cfg.style, STYLES["bold_pop"])
    highlight = cfg.highlight_color
    if cfg.style in STYLE_HIGHLIGHT_DEFAULTS and cfg.highlight_color.upper() == "#FFE14D":
        highlight = STYLE_HIGHLIGHT_DEFAULTS[cfg.style]
    font_size = max(18, int(round(preset.size_ratio * height * cfg.font_scale)))
    outline = max(1.0, round(preset.outline_ratio * font_size, 1)) if not preset.box else round(preset.outline_ratio * font_size, 1)
    base_font = cfg.font or preset.font
    emph_color = "#3CFF7A" if highlight.upper() != "#3CFF7A" else "#FFE14D"

    border_style = 3 if preset.box else 1
    outline_col = _ass_color(preset.box_color, preset.box_alpha) if preset.box else _ass_color(
        NEON_GLOW if preset.glow else cfg.outline_color
    )
    back_col = _ass_color("#000000", 0x60)
    y = (y_override if y_override is not None else POSITION_Y.get(cfg.position, 0.70)) * height
    x = width / 2

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{base_font},{font_size},{_ass_color(cfg.text_color)},{_ass_color(highlight)},"
        f"{outline_col},{back_col},{-1 if preset.bold else 0},0,0,0,100,100,{preset.spacing},0,"
        f"{border_style},{outline},{preset.shadow},5,20,20,20,1",
        f"Style: CapDeva,{preset.deva_font},{font_size},{_ass_color(cfg.text_color)},{_ass_color(highlight)},"
        f"{outline_col},{back_col},{-1 if preset.bold else 0},0,0,0,100,100,0,0,"
        f"{border_style},{outline},{preset.shadow},5,20,20,20,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events: list[str] = []
    hl = _ass_inline_color(highlight)
    base = _ass_inline_color(cfg.text_color)
    emph = _ass_inline_color(emph_color)
    blur_tag = f"\\blur{preset.blur}" if preset.blur else ""

    for li, line in enumerate(lines):
        next_start = lines[li + 1].start if li + 1 < len(lines) else clip_duration
        line_end = min(line.end + 0.35, next_start) if next_start > line.end else line.end
        deva = has_devanagari(line.text)
        style = "CapDeva" if deva else "Cap"
        max_chars = _max_chars(cfg, preset, width, height, deva)
        rows = _split_rows(line.words, cfg.max_lines if len(line.text) > max_chars else 1)
        longest_row = max(len(" ".join(line.words[i].text for i in r)) for r in rows)
        shrink = min(1.0, max_chars / max(longest_row, 1))
        base_scale = int(shrink * 100)
        scale_tag = f"\\fscx{base_scale}\\fscy{base_scale}" if shrink < 0.98 else ""

        # One event per word-state so the active word can be highlighted.
        states = list(range(len(line.words))) if preset.highlight != "none" else [None]
        for si, active in enumerate(states):
            if active is None:
                ev_start, ev_end = line.start, line_end
            else:
                ev_start = line.words[active].start if si > 0 else line.start
                ev_end = line.words[active + 1].start if active + 1 < len(line.words) else line_end
            if ev_end - ev_start < 0.02:
                continue
            parts = []
            for ri, row in enumerate(rows):
                row_parts = []
                for wi in row:
                    w = line.words[wi]
                    txt = _escape(_display(w.text, cfg, preset))
                    if active is not None and wi == active:
                        tags = f"\\c{hl}"
                        if preset.pop:
                            big = int(base_scale * 1.12)
                            tags += f"\\fscx{big}\\fscy{big}\\t(0,90,\\fscx{base_scale}\\fscy{base_scale})"
                        if preset.shake:
                            tags += "\\frz-2\\t(0,120,\\frz0)"
                        row_parts.append(f"{{{tags}}}{txt}{{\\r{style}{blur_tag}{scale_tag}}}")
                    elif preset.highlight == "karaoke" and active is not None and wi < active:
                        row_parts.append(f"{{\\c{hl}}}{txt}{{\\c{base}}}")
                    elif w.emphasis:
                        row_parts.append(f"{{\\c{emph}}}{txt}{{\\c{base}}}")
                    else:
                        row_parts.append(txt)
                parts.append(" ".join(row_parts))
            text = "\\N".join(parts)
            fade = "\\fad(60,0)" if si == 0 else ""
            events.append(
                f"Dialogue: 0,{_ass_time(ev_start)},{_ass_time(ev_end)},{style},,0,0,0,,"
                f"{{\\an5\\pos({x:.0f},{y:.0f}){blur_tag}{scale_tag}{fade}}}{text}"
            )
    return "\n".join(header + events) + "\n"


def _wrap_title(text: str, max_chars: int) -> list[str]:
    words, rows, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            rows.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        rows.append(cur)
    if len(rows) > 3:  # keep it a hook, not a paragraph
        rows = rows[:3]
        rows[-1] = rows[-1].rstrip(".,") + "..."
    return rows


def title_events(title: str, cfg: CaptionSettings, width: int, height: int, clip_duration: float, top_y: float) -> tuple[list[str], list[str]]:
    """ASS style + events for the hook title: dark text on a white box at the
    top of the frame, for the first `title_seconds` (0 = whole clip)."""
    text = (to_roman(title) if cfg.script == "roman" else title).strip()
    if not text:
        return [], []
    font = "Mukta ExtraBold"
    size = max(18, int(round(0.036 * height)))
    max_chars = max(10, int((width * 0.84) / (0.55 * size)))
    rows = _wrap_title(text, max_chars)
    end = clip_duration if cfg.title_seconds <= 0 else min(cfg.title_seconds, clip_duration)
    style = (
        f"Style: Title,{font},{size},&H00111111,&H00111111,&H00FFFFFF,&H00FFFFFF,0,0,0,0,100,100,0,0,"
        f"3,{max(2, int(size * 0.22))},0,8,40,40,20,1"
    )
    body = "\\N".join(_escape(r) for r in rows)
    event = (
        f"Dialogue: 1,{_ass_time(0)},{_ass_time(end)},Title,,0,0,0,,"
        f"{{\\an8\\pos({width / 2:.0f},{top_y * height:.0f})\\fad(120,200)}}{body}"
    )
    return [style], [event]


def build_srt(lines: list[CapLine], clip_duration: float) -> str:
    out = []
    for i, line in enumerate(lines, start=1):
        nxt = lines[i].start if i < len(lines) else clip_duration
        end = min(line.end + 0.3, nxt) if nxt > line.end else line.end
        out.append(f"{i}\n{_srt_time(line.start)} --> {_srt_time(end)}\n{line.text}\n")
    return "\n".join(out)


def _srt_time(t: float) -> str:
    ms = int(round(max(t, 0) * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_caption_files(
    words: list,
    clip_start: float,
    clip_end: float,
    cfg: CaptionSettings,
    width: int,
    height: int,
    ass_path: Path,
    srt_path: Path,
    y_override: float | None = None,
    title: str = "",
    title_top: float = 0.06,
) -> tuple[Path | None, Path]:
    """Write <clip>.ass (burn-in, only if captions or the hook title are on)
    and <clip>.srt (always -- handy for uploading captions separately).
    UTF-8 explicitly: Windows' default code page can't encode Devanagari."""
    cap_words = prepare_words(words, clip_start, clip_end, cfg)
    lines = group_lines(cap_words, cfg, width, height)
    duration = clip_end - clip_start
    srt_path.write_text(build_srt(lines, duration), encoding="utf-8")
    want_captions = cfg.enabled and cfg.style != "none" and bool(lines)
    want_title = cfg.title_overlay and bool(title.strip())
    if not want_captions and not want_title:
        return None, srt_path
    ass = build_ass(lines if want_captions else [], cfg, width, height, duration, y_override)
    if want_title:
        t_styles, t_events = title_events(title, cfg, width, height, duration, title_top)
        head, events = ass.split("[Events]\n", 1)
        head = head.rstrip("\n") + "\n" + "\n".join(t_styles) + "\n\n"
        ass = head + "[Events]\n" + events.rstrip("\n") + "\n" + "\n".join(t_events) + "\n"
    ass_path.write_text(ass, encoding="utf-8-sig")
    return ass_path, srt_path
