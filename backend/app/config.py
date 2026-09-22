"""
Central configuration for ClipForge.

Everything tunable lives here and is read from environment variables / a .env
file (see .env.example). Nothing about model choice, quality mode, or paths
should be hard-coded elsewhere in the pipeline -- add a setting here instead.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class QualityMode(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    HIGH_QUALITY = "high_quality"
    MAXIMUM_QUALITY = "maximum_quality"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLIPFORGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    # Storage
    data_dir: Path = Path("./data")

    # CORS
    frontend_origin: str = "http://localhost:5173"

    # Local AI
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    # auto | tiny | base | small | medium | large-v3-turbo | large-v3.
    # "auto" = large-v3-turbo on an NVIDIA GPU with >=6 GB VRAM, else medium
    # (small proved too inaccurate for real Hinglish gameplay commentary).
    whisper_model_size: str = "auto"
    # auto | cuda | cpu -- "auto" prefers the GPU and falls back to CPU if the
    # CUDA runtime is unusable; set "cpu" to skip the GPU attempt entirely.
    whisper_device: str = "auto"
    quality_mode: QualityMode = QualityMode.BALANCED
    # Language hint for transcription: "" = auto-detect (recommended for
    # Hinglish), or an ISO code like "hi" / "en".
    whisper_language: str = ""
    # Optional text to bias Whisper's vocabulary/spelling (e.g. game names,
    # your channel's slang). Leave empty unless you need it.
    whisper_initial_prompt: str = ""
    # Optional override for the ffmpeg binary. Empty = PATH, then the bundled
    # imageio-ffmpeg build.
    ffmpeg_path: str = ""
    # auto | nvenc | x264 -- "auto" tries NVIDIA hardware encoding when the
    # GPU supports it and silently falls back to x264 if it fails.
    video_encoder: str = "auto"
    # Browser to borrow YouTube cookies from when YouTube demands a sign-in
    # check (firefox | edge | chrome | brave). Empty = don't use cookies.
    youtube_cookies_browser: str = ""
    # Serve the built frontend (backend/app/static) at "/" -- single-process
    # production mode. The Vite dev server still works independently.
    serve_frontend: bool = True

    @field_validator("data_dir")
    @classmethod
    def _absolute_data_dir(cls, v: Path) -> Path:
        # Always absolute: ffmpeg runs with the render folder as its working
        # directory, so a relative "./data/..." source path would point at
        # the wrong place (this broke every render on Windows).
        return Path(v).expanduser().resolve()

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "clipforge.db"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(parents=True, exist_ok=True)


settings = Settings()
