"""
Central configuration for ClipForge.

Everything tunable lives here and is read from environment variables / a .env
file (see .env.example). Nothing about model choice, quality mode, or paths
should be hard-coded elsewhere in the pipeline -- add a setting here instead.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

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
    whisper_model_size: str = "base"  # tiny | base | small | medium | large-v3
    quality_mode: QualityMode = QualityMode.BALANCED

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
