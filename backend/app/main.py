"""ClipForge backend entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.config import settings
from app.db import init_db
from app.errors import ClipForgeError, clipforge_error_handler, unhandled_error_handler
from app.logging_config import configure_logging, get_logger
from app.routers import clips, ingest, jobs as jobs_router, moments, presets, projects, system, transcription

settings.ensure_dirs()
configure_logging(settings.data_dir / "logs", settings.log_level)
logger = get_logger("main")

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app import jobs, pipeline  # noqa: F401 - registers job kinds
    from app.tools import register_gpu_dlls

    init_db()
    try:
        pipeline.cleanup_orphans()
    except Exception:  # pragma: no cover
        logger.exception("Orphan cleanup failed")
    register_gpu_dlls()
    jobs.start_workers()
    logger.info("ClipForge backend starting. Data dir: %s", settings.data_dir.resolve())
    logger.info(
        "Quality mode: %s | Whisper model: %s | Ollama model: %s (%s)",
        settings.quality_mode.value,
        settings.whisper_model_size,
        settings.ollama_model,
        settings.ollama_host,
    )
    yield
    jobs.stop_workers()


app = FastAPI(
    title="ClipForge API",
    description="Local-first AI video clipping backend.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(ClipForgeError, clipforge_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(system.router)
app.include_router(projects.router)
app.include_router(ingest.router)
app.include_router(transcription.router)
app.include_router(moments.router)
app.include_router(clips.router)
app.include_router(jobs_router.router)
app.include_router(presets.router)


def _frontend_available() -> bool:
    return settings.serve_frontend and (STATIC_DIR / "index.html").exists()


@app.get("/", include_in_schema=False)
def root():
    if _frontend_available():
        return FileResponse(STATIC_DIR / "index.html")
    return {"name": "ClipForge API", "version": "1.0.0", "docs": "/docs"}


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str, request: Request):
    """Serve the built frontend (single-process production mode). Unknown
    non-API paths get index.html so client-side routes survive a refresh."""
    if full_path.startswith("api/") or not _frontend_available():
        return JSONResponse(status_code=404, content={"error": "Not found."})
    candidate = (STATIC_DIR / full_path).resolve()
    if candidate.is_file() and STATIC_DIR in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(STATIC_DIR / "index.html")
