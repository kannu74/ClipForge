from types import SimpleNamespace

from app.boundaries import fit_window, padded_times
from app.captions import build_ass, group_lines, prepare_words
from app.duration_presets import DurationPreset, resolve_bounds
from app.project_settings import CaptionSettings, FacecamRect, ReframeSettings
from app.reframe import Analysis, output_size, plan
from app.translit import has_devanagari, to_roman
from app.units import build_units, words_in_range


def _w(word, s, e):
    return {"word": word, "start": s, "end": e}


# --- units ---

def test_units_split_long_segment_at_sentences_and_pauses():
    seg = {
        "id": 0, "start": 0.0, "end": 12.0, "text": "x",
        "words": [
            _w("bhai", 0.0, 0.3), _w("sun.", 0.3, 0.6),
            _w("ye", 0.7, 0.9), _w("dekho", 0.9, 1.3),
            # 1.5s pause -> new unit even without punctuation
            _w("wait", 2.8, 3.1), _w("what?!", 3.1, 3.6),
        ],
    }
    units = build_units([seg])
    assert [u.text for u in units] == ["bhai sun.", "ye dekho", "wait what?!"]
    assert units[2].start == 2.8 and units[2].end == 3.6


def test_units_retime_edited_segments_evenly():
    seg = {"id": 3, "start": 10.0, "end": 12.0, "text": "bhai kya scene hai", "edited": True,
           "words": [_w("totally", 10.0, 12.0)]}
    units = build_units([seg])
    words = [w.word for u in units for w in u.words]
    assert words == ["bhai", "kya", "scene", "hai"]
    assert units[0].start == 10.0 and abs(units[-1].end - 12.0) < 0.01


def test_words_in_range_uses_midpoints():
    units = build_units([{"id": 0, "start": 0, "end": 3, "text": "a b c",
                          "words": [_w("a", 0, 1), _w("b", 1, 2), _w("c", 2, 3)]}])
    assert [w.word for w in words_in_range(units, 0.9, 2.2)] == ["b"]


# --- transliteration ---

def test_roman_transliteration_keeps_english_and_uses_casual_spellings():
    assert to_roman("भाई ये क्या हो रहा है") == "bhai ye kya ho raha hai"
    assert to_roman("करना पड़ेगा") == "karna padega"
    assert to_roman("that was insane यार") == "that was insane yaar"
    assert not has_devanagari(to_roman("मुझे समझ नहीं आया"))


# --- captions ---

def test_caption_lines_respect_word_budget_and_sentence_breaks():
    cfg = CaptionSettings(words_per_line=3)
    words = prepare_words(
        [_w(t, i * 0.4, i * 0.4 + 0.35) for i, t in enumerate("no way bro. that was so insane man".split())],
        0.0, 10.0, cfg,
    )
    lines = group_lines(words, cfg, 1080, 1920)
    texts = [ln.text for ln in lines]
    assert texts[0] == "no way bro."  # sentence end closes the line
    assert all(len(ln.words) <= 4 for ln in lines)
    assert " ".join(texts) == "no way bro. that was so insane man"


def test_caption_roman_script_option_and_relative_timing():
    cfg = CaptionSettings(script="roman")
    words = prepare_words([_w("क्या", 10.5, 10.9), _w("बात", 11.0, 11.4)], 10.0, 20.0, cfg)
    assert [w.text for w in words] == ["kya", "baat"]
    assert words[0].start == 0.5


def test_ass_uses_devanagari_font_for_hindi_lines():
    cfg = CaptionSettings(style="horror")  # Anton has no Devanagari glyphs
    words = prepare_words([_w("भूत", 0.0, 0.5), _w("है", 0.5, 1.0)], 0.0, 2.0, cfg)
    ass = build_ass(group_lines(words, cfg, 1080, 1920), cfg, 1080, 1920, 2.0)
    assert "Style: CapDeva,Mukta ExtraBold" in ass
    dialogue = [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]
    assert dialogue and all(",CapDeva," in d for d in dialogue)
    assert "\\c&H" in dialogue[0]  # active word highlighted


# --- duration fitting ---

def _u(s, e, t="x"):
    return SimpleNamespace(start=s, end=e, text=t)


def test_fit_window_grows_toward_preferred_and_keeps_peak():
    units = [_u(i * 3.0, i * 3.0 + 2.8) for i in range(20)]
    bounds = resolve_bounds(DurationPreset.SHORT)  # 20-35, preferred 28
    fw = fit_window(units, 10, 10, 10, bounds)
    dur = units[fw.end_idx].end - units[fw.start_idx].start
    assert 20 <= dur <= 35
    assert fw.start_idx <= 10 <= fw.end_idx
    # roughly 40% setup before the peak
    setup = units[10].start - units[fw.start_idx].start
    assert 0.25 <= setup / dur <= 0.6


def test_fit_window_does_not_cross_long_silence_when_long_enough():
    units = [_u(0, 5), _u(5.2, 10), _u(10.2, 15), _u(30, 35), _u(35.2, 40)]
    bounds = resolve_bounds(DurationPreset.CUSTOM, custom_min=10, custom_max=40, custom_preferred=30)
    fw = fit_window(units, 1, 1, 1, bounds)
    assert fw.end_idx == 2  # stopped at the 15s gap


def test_padded_times_never_overlap_neighbours():
    units = [_u(0, 2), _u(2.05, 4), _u(4.1, 6)]
    s, e = padded_times(units, 1, 1)
    assert s >= 2.0 and e <= 4.1


# --- reframing plans ---

def test_output_sizes():
    assert output_size("9:16", 1080) == (1080, 1920)
    assert output_size("1:1", 720) == (720, 720)


def test_auto_plan_picks_split_for_facecam_and_blur_for_no_face(tmp_path):
    cam = Analysis(kind="facecam", facecam={"x": 0.8, "y": 0.7, "w": 0.18, "h": 0.28}, track=[], face_ratio=1, samples=10)
    p = plan(ReframeSettings(), 1920, 1080, 1080, 1920, cam, tmp_path, "c1")
    assert p.mode == "split" and "vstack" in p.filter_complex and p.caption_y and 0.3 < p.caption_y < 0.5
    none = Analysis(kind="none", facecam=None, track=[], face_ratio=0, samples=10)
    p2 = plan(ReframeSettings(), 1920, 1080, 1080, 1920, none, tmp_path, "c1")
    assert p2.mode == "fit_blur" and "boxblur" in p2.filter_complex


def test_track_plan_writes_sendcmd_file(tmp_path):
    talk = Analysis(kind="talking", facecam=None, track=[(0.0, 0.3), (0.5, 0.35), (1.0, 0.6)], face_ratio=1, samples=3)
    p = plan(ReframeSettings(mode="track"), 1920, 1080, 1080, 1920, talk, tmp_path, "c2")
    assert p.mode == "track" and p.sendcmd_file
    lines = (tmp_path / p.sendcmd_file).read_text().strip().splitlines()
    xs = [int(ln.split()[-1].rstrip(";")) for ln in lines]
    assert xs == sorted(xs)  # face moved right -> crop moves right, monotonic
    assert all(0 <= x <= 1920 - 606 for x in xs)


def test_manual_split_uses_given_facecam_rect(tmp_path):
    cfg = ReframeSettings(mode="split", facecam=FacecamRect(x=0.0, y=0.0, w=0.25, h=0.3), facecam_on_top=False)
    p = plan(cfg, 1920, 1080, 1080, 1920, None, tmp_path, "c3")
    assert p.mode == "split" and "[game][cam]vstack" in p.filter_complex


def _overlaps(crop, cam):
    gw, gh, gx, gy = crop
    cx, cy, cw, ch = cam
    return cx < gx + gw and cx + cw > gx and cy < gy + gh and cy + ch > gy


def test_game_crop_excludes_facecam_for_every_position():
    from app.reframe import _game_crop, facecam_position
    cfg = ReframeSettings()
    W, H = 1920, 1080
    cases = {
        "bottom-center": (720, 700, 480, 380),
        "bottom-right": (1500, 720, 400, 340),
        "top-left": (20, 20, 420, 300),
    }
    for label, cam in cases.items():
        gw, gh, gx, gy, hidden = _game_crop(cfg, cam, W, H, 1080 / 1344)
        assert hidden is None, label
        assert not _overlaps((gw, gh, gx, gy), cam), label
        assert 0 <= gx and gx + gw <= W + 1 and 0 <= gy and gy + gh <= H + 1, label
        assert facecam_position(FacecamRect(x=cam[0] / W, y=cam[1] / H, w=cam[2] / W, h=cam[3] / H)) == label


def test_game_crop_blurs_facecam_when_it_cannot_be_avoided():
    from app.reframe import _game_crop
    # A huge cam in the middle of the frame leaves no clean region.
    gw, gh, gx, gy, hidden = _game_crop(ReframeSettings(), (400, 200, 1100, 700), 1920, 1080, 1080 / 1344)
    assert hidden is not None
