from app import social
import app.transcription as transcription_module
from app.captions import build_ass, group_lines, prepare_words
from app.project_settings import CaptionSettings
from app.translit import mask_profanity, normalize_spelling

from tests.test_clips_router import ExcitingFakeEngine, _setup_project_with_moments


def _words(text: str) -> list[dict]:
    return [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, w in enumerate(text.split())]


def test_normalize_spelling_unifies_variants_and_keeps_case_and_punctuation():
    assert normalize_spelling("Nahin,") == "Nahi,"
    assert normalize_spelling("kyaa?") == "kya?"
    assert normalize_spelling("YEH") == "YE"
    # Ambiguous short words are never rewritten.
    assert normalize_spelling("me") == "me"
    assert normalize_spelling("kiya") == "kiya"


def test_mask_profanity_keeps_first_and_last_letter():
    assert mask_profanity("fucking!") == "f*****g!"
    assert mask_profanity("bhai") == "bhai"


def test_new_caption_options_apply_to_words():
    cfg = CaptionSettings(unify_spelling=True, mask_profanity=True)
    words = prepare_words(_words("bhai nhi yaar shit"), 0, 3, cfg)
    assert [w.text for w in words] == ["bhai", "nahi", "yaar", "s**t"]
    plain = prepare_words(_words("bhai nhi"), 0, 3, CaptionSettings())
    assert plain[1].text == "nhi"


def test_every_new_style_builds_valid_ass():
    for style in ("hormozi", "highlighter", "typewriter", "meme", "cinema"):
        cfg = CaptionSettings(style=style)
        lines = group_lines(prepare_words(_words("bhai wait no way this is insane"), 0, 4, cfg), cfg, 1080, 1920)
        ass = build_ass(lines, cfg, 1080, 1920, 4)
        assert "[Events]" in ass and "Dialogue:" in ass, style
    box = build_ass(
        group_lines(prepare_words(_words("a b c"), 0, 2, CaptionSettings(style="highlighter")), CaptionSettings(style="highlighter"), 1080, 1920),
        CaptionSettings(style="highlighter"), 1080, 1920, 2,
    )
    assert "Style: CapBox," in box and "\\rCapBox" in box
    typed = build_ass(
        group_lines(prepare_words(_words("a b c"), 0, 2, CaptionSettings(style="typewriter")), CaptionSettings(style="typewriter"), 1080, 1920),
        CaptionSettings(style="typewriter"), 1080, 1920, 2,
    )
    assert "\\alpha&HFF&" in typed  # unspoken words hidden


def test_social_suggestions_are_grounded_and_ranked():
    excerpt = "bhai ye ghost dekho ghost! WAIT NO WAY, the ghost is behind me. bhai yaar kya hai ye"
    out = social.suggest(excerpt, "Ghost behind me?!", "scare", "horror_gaming")
    tags = [h["tag"] for h in out["hashtags"]]
    assert "#horrorgaming" in tags and "#ghost" in tags and "#hinglish" in tags
    assert len(tags) == len(set(tags)) <= 12
    assert out["captions"][0]["text"] == "Ghost behind me?!"


def test_social_llm_falls_back_when_ollama_is_down(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("no ollama")

    monkeypatch.setattr(social.requests, "post", boom)
    out = social.suggest_with_llm("we clutch it", "Clutch!", "clutch", "gaming")
    assert out["source"] == "local-rules" and "note" in out and out["hashtags"]


def test_extend_endpoint_grows_clip_and_reports_limits(client, sample_video, monkeypatch):
    project_id = _setup_project_with_moments(client, sample_video, monkeypatch)
    created = client.post(f"/api/projects/{project_id}/clips", json={"start": 1.6, "end": 2.6, "render": False})
    assert created.status_code == 201, created.text
    clip = created.json()

    r = client.post(f"/api/projects/{project_id}/clips/{clip['id']}/extend", json={"before": 1.0, "after": 1.0, "render": False})
    assert r.status_code == 200, r.text
    grown = r.json()
    assert grown["start"] < clip["start"] and grown["end"] > clip["end"]
    assert grown["edited"] is True and grown["duration_explanation"].startswith("Extended")

    # Nothing to add once it reaches the start of the video.
    edge = client.post(f"/api/projects/{project_id}/clips", json={"start": 0, "end": 2, "render": False}).json()
    none = client.post(f"/api/projects/{project_id}/clips/{edge['id']}/extend", json={"before": 5, "render": False})
    assert none.status_code == 400 or none.status_code == 422, none.text


def test_social_endpoint(client, sample_video, monkeypatch):
    project_id = _setup_project_with_moments(client, sample_video, monkeypatch)
    clip = client.post(f"/api/projects/{project_id}/clips", json={"start": 1.5, "end": 3.0, "title": "Clutch!", "render": False}).json()
    r = client.get(f"/api/projects/{project_id}/clips/{clip['id']}/social")
    assert r.status_code == 200
    body = r.json()
    assert body["captions"] and body["hashtags"]


def test_batch_clips_are_numbered_in_order_and_validated_together(client, sample_video, monkeypatch):
    project_id = _setup_project_with_moments(client, sample_video, monkeypatch)
    r = client.post(
        f"/api/projects/{project_id}/clips/batch",
        json={"clips": [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 4.0, "title": "Mine"}], "render": False},
    )
    assert r.status_code == 201, r.text
    made = r.json()
    assert [c["title"] for c in made] == ["Clip 1", "Mine"] and all(c["origin"] == "manual" for c in made)
    listed = client.get(f"/api/projects/{project_id}/clips").json()["clips"]
    assert [c["title"] for c in listed if c["origin"] == "manual"][:2] == ["Clip 1", "Mine"]

    before = len(listed)
    bad = client.post(
        f"/api/projects/{project_id}/clips/batch",
        json={"clips": [{"start": 0.0, "end": 2.0}, {"start": 1.0, "end": 1.2}], "render": False},
    )
    assert bad.status_code in (400, 422)
    assert len(client.get(f"/api/projects/{project_id}/clips").json()["clips"]) == before  # nothing half-added


def test_review_preset_and_content_type_are_valid():
    from app import presets
    from app.moments import CONTENT_TYPE_CATEGORIES, KEYWORD_LEXICON

    p = next(p for p in presets.BUILT_IN if p["id"] == "builtin-review")
    presets._clean(p["settings"])  # validates against ProjectSettings
    assert set(CONTENT_TYPE_CATEGORIES["review"]) <= set(KEYWORD_LEXICON) | {"story"}


def test_manual_mode_transcribes_but_picks_no_clips(client, sample_video, monkeypatch):
    from app import jobs

    monkeypatch.setattr(transcription_module, "FasterWhisperEngine", ExcitingFakeEngine)
    pid = client.post(
        "/api/projects", json={"name": "Manual", "content_type": "review", "settings": {"clip_mode": "manual"}}
    ).json()["id"]
    with sample_video.open("rb") as f:
        client.post(f"/api/projects/{pid}/upload", files={"file": ("s.mp4", f, "video/mp4")})
    job = client.post(f"/api/projects/{pid}/process", json={}).json()
    assert jobs.wait_idle(timeout=120)
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "done"
    assert client.get(f"/api/projects/{pid}/transcript").status_code == 200  # transcribed
    assert client.get(f"/api/projects/{pid}/clips").status_code == 404  # nothing auto-picked
    made = client.post(f"/api/projects/{pid}/clips/batch", json={"clips": [{"start": 0, "end": 3}], "render": False})
    assert made.status_code == 201 and made.json()[0]["transcript_excerpt"]
