"""
Phase 7 -- smart reframing.

Turns a (usually 16:9) source into the output aspect ratio without losing the
action. Modes:

  fill      crop to the target aspect around a fixed horizontal focus point
  track     crop that follows the speaker's face (smoothed, with a dead-zone
            so the frame doesn't jitter on every small head movement)
  split     gaming layout: the streamer's facecam in one panel, the
            gameplay in the other, captions on the seam
  fit_blur  the whole frame, scaled to fit, over a blurred copy of itself --
            never crops anything, the safe choice for busy gameplay
  original  the whole frame letterboxed on black
  auto      decide from the content: consistent small face near a frame edge
            => split (facecam); large face => track; no face => fit_blur

Face detection uses OpenCV's YuNet model (bundled, ~230 KB, MIT licensed) on
frames sampled at 2 fps; decoding goes through ffmpeg so it works on any
input ffmpeg can read.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from app import tools
from app.logging_config import get_logger
from app.project_settings import FacecamRect, ReframeSettings

logger = get_logger("reframe")

MODEL_PATH = Path(__file__).resolve().parent / "assets" / "models" / "face_detection_yunet_2023mar.onnx"
SAMPLE_FPS = 2.0
ANALYSIS_WIDTH = 640
MIN_FACE_SCORE = 0.75

OUTPUT_SIZES = {
    ("9:16", 1080): (1080, 1920), ("9:16", 720): (720, 1280),
    ("1:1", 1080): (1080, 1080), ("1:1", 720): (720, 720),
    ("4:5", 1080): (1080, 1350), ("4:5", 720): (720, 900),
    ("16:9", 1080): (1920, 1080), ("16:9", 720): (1280, 720),
}


def output_size(aspect: str, resolution: int) -> tuple[int, int]:
    return OUTPUT_SIZES.get((aspect, resolution), (1080, 1920))


@dataclass
class Face:
    x: float  # normalized top-left
    y: float
    w: float
    h: float
    score: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> float:
        return self.w * self.h


@dataclass
class FaceSample:
    t: float  # seconds from clip start
    faces: list[Face] = field(default_factory=list)


@dataclass
class Analysis:
    kind: str  # facecam | talking | none
    facecam: dict | None
    track: list[tuple[float, float]]  # (t, normalized center x)
    face_ratio: float  # share of samples with any face
    samples: int


def _even(v: float) -> int:
    return max(2, int(round(v / 2.0)) * 2)


def sample_faces(src: Path, start: float, end: float, src_w: int, src_h: int) -> list[FaceSample]:
    import subprocess

    try:
        import cv2  # type: ignore
    except ImportError:
        logger.warning("OpenCV not installed -- smart reframing falls back to non-tracking modes.")
        return []
    if not MODEL_PATH.exists() or src_w <= 0 or src_h <= 0:
        return []

    aw = ANALYSIS_WIDTH
    ah = _even(aw * src_h / src_w)
    duration = max(end - start, 0.1)
    cmd = [
        tools.ffmpeg_path(), "-v", "error", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
        "-an", "-vf", f"fps={SAMPLE_FPS},scale={aw}:{ah}", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=tools.SUBPROCESS_FLAGS)
    tools.StderrDrain(proc.stderr)
    detector = cv2.FaceDetectorYN.create(str(MODEL_PATH), "", (aw, ah), 0.6, 0.3, 50)
    frame_bytes = aw * ah * 3
    samples: list[FaceSample] = []
    i = 0
    assert proc.stdout is not None
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(ah, aw, 3)
            _, dets = detector.detect(frame)
            faces = []
            if dets is not None:
                for d in dets:
                    x, y, w, h, score = float(d[0]), float(d[1]), float(d[2]), float(d[3]), float(d[-1])
                    if score < MIN_FACE_SCORE or w < 8 or h < 8:
                        continue
                    faces.append(Face(x / aw, y / ah, w / aw, h / ah, score))
            samples.append(FaceSample(t=i / SAMPLE_FPS, faces=faces))
            i += 1
    finally:
        proc.stdout.close()
        proc.wait()
    return samples


def _cluster_small_edge_faces(samples: list[FaceSample]) -> list[Face] | None:
    """The facecam signature: a smallish face that stays put, off-center."""
    cells: dict[tuple[int, int], list[Face]] = {}
    for s in samples:
        seen = set()
        for f in s.faces:
            if f.area > 0.05:
                continue
            key = (int(f.cx * 8), int(f.cy * 8))
            if key in seen:
                continue
            seen.add(key)
            cells.setdefault(key, []).append(f)
    if not cells:
        return None
    # Merge each cell with its neighbours so a face on a cell border counts once.
    best: list[Face] = []
    for (cx, cy) in cells:
        group = [f for (kx, ky), fs in cells.items() if abs(kx - cx) <= 1 and abs(ky - cy) <= 1 for f in fs]
        if len(group) > len(best):
            best = group
    if len(best) < max(3, 0.4 * len(samples)):
        return None
    mx = float(np.median([f.cx for f in best]))
    my = float(np.median([f.cy for f in best]))
    off_center = abs(mx - 0.5) > 0.18 or abs(my - 0.5) > 0.18
    if not off_center:
        return None
    return best


def facecam_rect_from_faces(faces: list[Face], src_w: int, src_h: int) -> FacecamRect:
    """Estimate the webcam overlay around a detected face: overlays are
    usually ~3x the face width and ~2.4x its height, with the face slightly
    above center."""
    fw = float(np.median([f.w for f in faces])) * src_w
    fh = float(np.median([f.h for f in faces])) * src_h
    cx = float(np.median([f.cx for f in faces])) * src_w
    cy = float(np.median([f.cy for f in faces])) * src_h
    w = min(fw * 3.2, src_w)
    h = min(fh * 2.6, src_h)
    x = min(max(cx - w / 2, 0), src_w - w)
    y = min(max(cy - h * 0.45, 0), src_h - h)
    return FacecamRect(x=x / src_w, y=y / src_h, w=w / src_w, h=h / src_h)


def _track_path(samples: list[FaceSample], crop_w_norm: float) -> list[tuple[float, float]]:
    """Smoothed horizontal crop center (normalized) over time."""
    raw: list[float | None] = []
    for s in samples:
        big = max(s.faces, key=lambda f: f.area, default=None)
        raw.append(big.cx if big else None)
    if not any(v is not None for v in raw):
        return []
    # Fill gaps by holding the last known position (then back-fill the start).
    filled: list[float] = []
    last = next(v for v in raw if v is not None)
    for v in raw:
        last = v if v is not None else last
        filled.append(last)
    # Dead-zone + easing: only move when the face leaves the middle 30% of
    # the crop, then glide there instead of jumping.
    dead = crop_w_norm * 0.15
    cur = filled[0]
    path: list[tuple[float, float]] = []
    for i, target in enumerate(filled):
        if abs(target - cur) > dead:
            cur += (target - cur) * 0.45
        half = crop_w_norm / 2
        cur = min(max(cur, half), 1 - half)
        path.append((i / SAMPLE_FPS, cur))
    return path


def analyze(src: Path, start: float, end: float, src_w: int, src_h: int, out_aspect: float, cache: Path | None = None) -> Analysis:
    key = f"{start:.2f}-{end:.2f}-{out_aspect:.4f}"
    if cache and cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("key") == key:
                a = data["analysis"]
                return Analysis(a["kind"], a["facecam"], [tuple(p) for p in a["track"]], a["face_ratio"], a["samples"])
        except Exception:
            pass
    samples = sample_faces(src, start, end, src_w, src_h)
    n = len(samples)
    with_face = sum(1 for s in samples if s.faces)
    face_ratio = with_face / n if n else 0.0
    facecam = None
    kind = "none"
    track: list[tuple[float, float]] = []
    cam_faces = _cluster_small_edge_faces(samples) if n else None
    if cam_faces:
        kind = "facecam"
        facecam = facecam_rect_from_faces(cam_faces, src_w, src_h).model_dump()
    elif n and face_ratio >= 0.5:
        big = [f for s in samples for f in s.faces if f.area >= 0.012]
        if len(big) >= 0.4 * n:
            kind = "talking"
            crop_w_norm = min(1.0, (src_h * out_aspect) / src_w)
            track = _track_path(samples, crop_w_norm)
    result = Analysis(kind=kind, facecam=facecam, track=track, face_ratio=round(face_ratio, 2), samples=n)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "analysis": asdict(result)}), encoding="utf-8")
    return result


# --- filter graphs ---

@dataclass
class ReframePlan:
    mode: str                 # resolved mode actually used
    filter_complex: str       # input [0:v] -> output [vout] (before captions)
    caption_y: float | None   # override for caption vertical position (split seam)
    note: str                 # plain-language explanation for the UI
    sendcmd_file: str | None = None


def _floor_even(v: float) -> int:
    return max(2, int(v) - (int(v) % 2))


def _fill_crop(src_w: int, src_h: int, out_w: int, out_h: int) -> tuple[int, int]:
    """Largest even-sized crop of the source with the output's aspect ratio."""
    target = out_w / out_h
    if src_w / src_h > target:
        return min(_floor_even(src_h * target), _floor_even(src_w)), _floor_even(src_h)
    return _floor_even(src_w), min(_floor_even(src_w / target), _floor_even(src_h))


def plan(
    cfg: ReframeSettings,
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    analysis: Analysis | None,
    workdir: Path,
    clip_id: str,
) -> ReframePlan:
    mode = cfg.mode
    note = ""
    src_aspect = src_w / src_h if src_h else 16 / 9
    out_aspect = out_w / out_h

    if mode == "auto":
        if abs(src_aspect - out_aspect) < 0.03:
            mode, note = "fill", "Source already matches the output shape."
        elif analysis and analysis.kind == "facecam" and out_aspect < 1:
            mode, note = "split", "Detected a facecam -- facecam on top, gameplay below."
        elif analysis and analysis.kind == "talking":
            mode, note = "track", "Detected a speaker -- the crop follows their face."
        else:
            mode, note = "fit_blur", "No clear face found -- showing the full frame over a blurred background so no action is cut off."
    if mode == "split" and out_aspect >= 1:
        mode, note = "fit_blur", "Split layout needs a vertical output; used full-frame instead."
    if mode == "split":
        rect = cfg.facecam or (FacecamRect(**analysis.facecam) if analysis and analysis.facecam else None)
        if rect is None:
            mode, note = "fit_blur", "Split layout needs a facecam area -- none was detected or set, so the full frame is shown instead. Mark the facecam in the editor to use split."
        else:
            return _split(cfg, rect, src_w, src_h, out_w, out_h, note or "Facecam on top, gameplay below.")
    if mode == "track":
        path = analysis.track if analysis else []
        if not path:
            mode, note = "fill", note or "Couldn't find a face to follow -- used a centered crop."
        else:
            return _track(path, src_w, src_h, out_w, out_h, workdir, clip_id, note or "Crop follows the speaker's face.")
    if mode == "fill":
        cw, ch = _fill_crop(src_w, src_h, out_w, out_h)
        x = int(round((src_w - cw) * cfg.focus_x))
        y = int(round((src_h - ch) / 2))
        fc = f"[0:v]crop={cw}:{ch}:{x}:{y},scale={out_w}:{out_h}:flags=lanczos,setsar=1[vout]"
        return ReframePlan("fill", fc, None, note or "Cropped to fill the frame.")
    if mode == "original":
        fc = (
            f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[vout]"
        )
        return ReframePlan("original", fc, None, note or "Full frame with black bars.")
    # fit_blur (default)
    bw, bh = _even(out_w / 4), _even(out_h / 4)
    fc = (
        f"[0:v]split=2[bgsrc][fgsrc];"
        f"[bgsrc]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
        f"boxblur=12:3,eq=brightness=-0.10:saturation=1.15,scale={out_w}:{out_h}[bg];"
        f"[fgsrc]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[vout]"
    )
    # Keep captions below the video band so they never cover the action.
    fg_h = min(out_h, out_w / src_aspect) if src_aspect > out_aspect else out_h
    band_bottom = (out_h + fg_h) / 2 / out_h
    cap_y = min(0.86, band_bottom + 0.06) if fg_h < out_h * 0.75 else None
    return ReframePlan("fit_blur", fc, cap_y, note or "Full frame over a blurred background.")


def _split(cfg: ReframeSettings, rect: FacecamRect, src_w: int, src_h: int, out_w: int, out_h: int, note: str) -> ReframePlan:
    top_h = _even(out_h * cfg.split_ratio)
    bot_h = out_h - top_h
    # Facecam panel: expand the marked rect to the panel's aspect ratio.
    rx, ry, rw, rh = rect.x * src_w, rect.y * src_h, rect.w * src_w, rect.h * src_h
    panel_aspect = out_w / top_h
    cx, cy = rx + rw / 2, ry + rh / 2
    if rw / rh < panel_aspect:
        rw = rh * panel_aspect
    else:
        rh = rw / panel_aspect
    rw, rh = min(rw, src_w), min(rh, src_h)
    rx = min(max(cx - rw / 2, 0), src_w - rw)
    ry = min(max(cy - rh / 2, 0), src_h - rh)
    cam = f"crop={_floor_even(rw)}:{_floor_even(rh)}:{int(rx)}:{int(ry)},scale={out_w}:{top_h}:flags=lanczos"
    # Gameplay panel: crop to its aspect around the focus point.
    g_aspect = out_w / bot_h
    gh = src_h
    gw = min(src_w, gh * g_aspect)
    if gw >= src_w:
        gw = src_w
        gh = min(src_h, gw / g_aspect)
    gx = (src_w - gw) * cfg.focus_x
    gy = (src_h - gh) / 2
    game = f"crop={_floor_even(gw)}:{_floor_even(gh)}:{int(gx)}:{int(gy)},scale={out_w}:{bot_h}:flags=lanczos"
    top, bottom = ("cam", "game") if cfg.facecam_on_top else ("game", "cam")
    fc = (
        f"[0:v]split=2[camsrc][gamesrc];[camsrc]{cam}[cam];[gamesrc]{game}[game];"
        f"[{top}][{bottom}]vstack=inputs=2,setsar=1[vout]"
    )
    seam = (top_h if cfg.facecam_on_top else bot_h) / out_h
    return ReframePlan("split", fc, seam, note)


def _track(path: list[tuple[float, float]], src_w: int, src_h: int, out_w: int, out_h: int, workdir: Path, clip_id: str, note: str) -> ReframePlan:
    cw, ch = _fill_crop(src_w, src_h, out_w, out_h)
    y = int(round((src_h - ch) / 2))
    max_x = src_w - cw

    def x_at(center_norm: float) -> int:
        return int(min(max(center_norm * src_w - cw / 2, 0), max_x))

    # Interpolate the 2 fps path to 10 updates/second for smooth motion.
    lines = []
    step = 0.1
    t_end = path[-1][0] + 1.0 / SAMPLE_FPS
    t = 0.0
    j = 0
    while t <= t_end + 1e-6:
        while j + 1 < len(path) and path[j + 1][0] <= t:
            j += 1
        if j + 1 < len(path):
            (t0, c0), (t1, c1) = path[j], path[j + 1]
            a = (t - t0) / (t1 - t0) if t1 > t0 else 0
            a = a * a * (3 - 2 * a)  # smoothstep easing
            c = c0 + (c1 - c0) * a
        else:
            c = path[-1][1]
        lines.append(f"{t:.2f} crop x {x_at(c)};")
        t = round(t + step, 2)
    cmd_name = f"{clip_id}.track.txt"
    (workdir / cmd_name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    x0 = x_at(path[0][1])
    fc = f"[0:v]sendcmd=f={cmd_name},crop={cw}:{ch}:{x0}:{y},scale={out_w}:{out_h}:flags=lanczos,setsar=1[vout]"
    return ReframePlan("track", fc, None, note, sendcmd_file=cmd_name)


def describe_modes() -> dict:
    return {
        "auto": "Pick automatically (facecam split / face tracking / full frame)",
        "fill": "Crop to fill",
        "track": "Follow the speaker's face",
        "split": "Facecam + gameplay split",
        "fit_blur": "Full frame, blurred background",
        "original": "Full frame, black bars",
    }


def aspect_value(aspect: str) -> float:
    a, b = aspect.split(":")
    return float(a) / float(b)

