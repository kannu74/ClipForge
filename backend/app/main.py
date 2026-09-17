"""ClipForge backend entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.errors import ClipForgeError, clipforge_error_handler, unhandled_error_handler
from app.logging_config import configure_logging, get_logger
from app.routers import projects, system

settings.ensure_dirs()
configure_logging(settings.data_dir / "logs", settings.log_level)
logger = get_logger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("ClipForge backend starting. Data dir: %s", settings.data_dir.resolve())
    logger.info(
        "Quality mode: %s | Whisper model: %s | Ollama model: %s (%s)",
        settings.quality_mode.value,
        settings.whisper_model_size,
        settings.ollama_model,
        settings.ollama_host,
    )
    yield


app = FastAPI(
    title="ClipForge API",
    description="Local-first AI video clipping backend.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(ClipForgeError, clipforge_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(system.router)
app.include_router(projects.router)


@app.get("/")
def root() -> dict:
    return {"name": "ClipForge API", "version": "0.1.0", "docs": "/docs"}
