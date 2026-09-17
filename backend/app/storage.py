"""
On-disk layout for a project's working data. Kept separate from db.py:
db.py is the source of truth for metadata/state, this module is the source
of truth for where files live on disk.

    data/projects/<id>/
        source/       original video (or downloaded YouTube video)
        transcript/   transcript.json, word-level segments
        moments/      detected + ranked moment candidates
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

SUBDIRS = ("source", "transcript", "moments", "clips", "renders")


def init_project_storage(project_id: str) -> Path:
    base = project_dir(project_id)
    base.mkdir(parents=True, exist_ok=True)
    for sub in SUBDIRS:
        (base / sub).mkdir(exist_ok=True)
    return base


def write_manifest(project_id: str, manifest: dict[str, Any]) -> None:
    base = init_project_storage(project_id)
    (base / "project.json").write_text(json.dumps(manifest, indent=2, default=str))


def read_manifest(project_id: str) -> dict[str, Any] | None:
    path = project_dir(project_id) / "project.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def delete_project_storage(project_id: str) -> None:
    import shutil

    base = project_dir(project_id)
    if base.exists():
        shutil.rmtree(base)
