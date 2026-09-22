"""
On-disk layout for a project's working data. Kept separate from db.py:
db.py is the source of truth for metadata/state, this module is the source
of truth for where files live on disk.

    data/projects/<id>/
        source/       original video (or downloaded YouTube video)
        transcript/   transcript.json (word-level segments)
        moments/      moments.json (detected candidate moments)
        clips/        generated clip candidates (pre-render working files)
        renders/      final rendered exports
        project.json  human-readable manifest mirroring the DB row, for
                       debugging / manual inspection / future import-export
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.db import project_dir

SUBDIRS = ("source", "transcript", "moments", "clips", "renders", "analysis")


def init_project_storage(project_id: str) -> Path:
    base = project_dir(project_id)
    base.mkdir(parents=True, exist_ok=True)
    for sub in SUBDIRS:
        (base / sub).mkdir(exist_ok=True)
    return base


def source_dir(project_id: str) -> Path:
    return project_dir(project_id) / "source"


def find_source_file(project_id: str) -> Path | None:
    d = source_dir(project_id)
    if not d.exists():
        return None
    candidates = [
        p for p in d.iterdir()
        if p.is_file() and not p.name.endswith((".part", ".ytdl", ".tmp")) and not p.name.startswith(".")
    ]
    candidates.sort(key=lambda p: (not p.name.startswith("source"), p.name))
    return candidates[0] if candidates else None


def transcript_path(project_id: str) -> Path:
    return project_dir(project_id) / "transcript" / "transcript.json"


def moments_path(project_id: str) -> Path:
    return project_dir(project_id) / "moments" / "moments.json"


def clips_path(project_id: str) -> Path:
    return project_dir(project_id) / "clips" / "clips.json"


def renders_dir(project_id: str) -> Path:
    d = project_dir(project_id) / "renders"
    d.mkdir(parents=True, exist_ok=True)
    return d


def analysis_dir(project_id: str) -> Path:
    d = project_dir(project_id) / "analysis"
    d.mkdir(parents=True, exist_ok=True)
    return d


def energy_path(project_id: str) -> Path:
    return analysis_dir(project_id) / "energy.json"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename so a crash mid-write never leaves a truncated file
    # that breaks the project on next load.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(project_id: str, manifest: dict[str, Any]) -> None:
    base = init_project_storage(project_id)
    (base / "project.json").write_text(json.dumps(manifest, indent=2, default=str, ensure_ascii=False), encoding="utf-8")


def read_manifest(project_id: str) -> dict[str, Any] | None:
    path = project_dir(project_id) / "project.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def delete_project_storage(project_id: str) -> None:
    import shutil

    base = project_dir(project_id)
    if base.exists():
        # Windows can briefly hold a lock on a file ffmpeg just closed; retry
        # a few times rather than failing the delete outright.
        import time

        for attempt in range(5):
            try:
                shutil.rmtree(base)
                return
            except OSError:
                if attempt == 4:
                    shutil.rmtree(base, ignore_errors=True)
                    return
                time.sleep(0.5)
