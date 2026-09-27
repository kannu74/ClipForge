"""
Phase 8 -- presets: named bundles of content type + clip/caption/framing
settings. A few built-in starting points for the content ClipForge targets,
plus the creator's own saved presets (SQLite).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from app import db
from app.errors import NotFoundError, ValidationFailedError
from app.project_settings import ProjectSettings, deep_merge

SCHEMA = """
CREATE TABLE IF NOT EXISTS presets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    content_type TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# Only the fields a preset should carry -- never a source range or model.
_PRESET_KEYS = ("clip_count", "duration_preset", "custom_min_seconds", "custom_max_seconds",
                "include_backup_clips", "auto_render", "clip_mode", "captions", "reframe", "render", "language")

BUILT_IN: list[dict] = [
    {
        "id": "builtin-horror",
        "name": "Horror Shorts",
        "content_type": "horror_gaming",
        "settings": {
            "duration_preset": "short",
            "captions": {"style": "horror", "uppercase": True, "title_overlay": True, "title_seconds": 3},
            "reframe": {"aspect": "9:16", "mode": "auto"},
        },
    },
    {
        "id": "builtin-gaming",
        "name": "Gaming Highlights",
        "content_type": "gaming",
        "settings": {
            "duration_preset": "short",
            "captions": {"style": "bold_pop", "uppercase": True},
            "reframe": {"aspect": "9:16", "mode": "auto"},
        },
    },
    {
        "id": "builtin-funny",
        "name": "Funny Moments",
        "content_type": "funny_gaming",
        "settings": {
            "duration_preset": "ultra_short",
            "captions": {"style": "karaoke", "uppercase": True, "title_overlay": True, "title_seconds": 3},
            "reframe": {"aspect": "9:16", "mode": "auto"},
        },
    },
    {
        "id": "builtin-talk",
        "name": "Podcast / Talking",
        "content_type": "commentary",
        "settings": {
            "duration_preset": "standard",
            "captions": {"style": "clean", "uppercase": False, "words_per_line": 5, "max_lines": 2},
            "reframe": {"aspect": "9:16", "mode": "track"},
        },
    },
    {
        "id": "builtin-review",
        "name": "Review / Info Video",
        "content_type": "review",
        "settings": {
            "duration_preset": "extended",
            "captions": {"style": "clean", "uppercase": False, "words_per_line": 4, "max_lines": 2,
                         "position": "lower", "title_overlay": True, "title_seconds": 4},
            # Reviews show footage the viewer needs to see whole: full frame over a blurred backdrop.
            "reframe": {"aspect": "9:16", "mode": "fit_blur"},
        },
    },
    {
        "id": "builtin-hinglish-reaction",
        "name": "Hinglish Reaction",
        "content_type": "reaction",
        "settings": {
            "duration_preset": "short",
            "captions": {"style": "bold_pop", "script": "roman", "uppercase": True},
            "reframe": {"aspect": "9:16", "mode": "auto"},
        },
    },
]


def init_table() -> None:
    with db.connection() as conn:
        conn.executescript(SCHEMA)


def _clean(settings: dict) -> dict:
    out = {k: v for k, v in settings.items() if k in _PRESET_KEYS}
    if isinstance(out.get("reframe"), dict):
        out["reframe"] = {**out["reframe"], "facecam": None}  # a facecam spot is per-video
    # Validate by building full settings.
    ProjectSettings(**deep_merge(ProjectSettings().model_dump(), out))
    return out


def list_presets() -> list[dict]:
    init_table()
    with db.connection() as conn:
        rows = conn.execute("SELECT * FROM presets ORDER BY created_at").fetchall()
    user = [
        {"id": r["id"], "name": r["name"], "content_type": r["content_type"],
         "settings": json.loads(r["settings_json"]), "builtin": False}
        for r in rows
    ]
    return [{**p, "builtin": True} for p in BUILT_IN] + user


def create_preset(name: str, content_type: str, settings: dict) -> dict:
    name = (name or "").strip()[:60]
    if not name:
        raise ValidationFailedError("Give the preset a name.")
    try:
        cleaned = _clean(settings or {})
    except Exception as exc:
        raise ValidationFailedError("Those settings aren't valid.", detail=str(exc))
    init_table()
    pid = "p" + uuid.uuid4().hex[:10]
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO presets (id, name, content_type, settings_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (pid, name, content_type, json.dumps(cleaned), datetime.now(timezone.utc).isoformat()),
        )
    return {"id": pid, "name": name, "content_type": content_type, "settings": cleaned, "builtin": False}


def delete_preset(preset_id: str) -> None:
    if preset_id.startswith("builtin-"):
        raise ValidationFailedError("Built-in presets can't be deleted.")
    init_table()
    with db.connection() as conn:
        cur = conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
        if cur.rowcount == 0:
            raise NotFoundError("That preset doesn't exist.")
