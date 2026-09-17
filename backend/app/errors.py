"""
Typed application errors and the FastAPI handler that turns them into
plain-language, actionable JSON responses.

Rule: never let a raw exception (CUDA error, ffmpeg stderr dump, stack
trace) reach the user. Raise one of these instead, or catch the low-level
error and re-raise as one of these with a human explanation.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class ClipForgeError(Exception):
    """Base class for all application errors with a user-facing message."""

    status_code = 500

    def __init__(self, message: str, *, suggestion: str | None = None, detail: str | None = None):
        self.message = message
        self.suggestion = suggestion
        self.detail = detail  # technical detail, logged but not required to be shown
        super().__init__(message)

    def to_payload(self) -> dict:
        payload = {"error": self.message}
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        return payload


class ValidationFailedError(ClipForgeError):
    status_code = 400


class NotFoundError(ClipForgeError):
    status_code = 404


class UnsupportedMediaError(ClipForgeError):
    status_code = 415


class ExternalToolMissingError(ClipForgeError):
    """A required local tool (ffmpeg, ollama, etc.) is missing or unreachable."""

    status_code = 503


class InsufficientResourcesError(ClipForgeError):
    """A model/operation needs more GPU/CPU/RAM than is currently available."""

    status_code = 507


async def clipforge_error_handler(request: Request, exc: ClipForgeError) -> JSONResponse:
    from app.logging_config import get_logger

    logger = get_logger("errors")
    logger.error("%s: %s (detail=%s)", type(exc).__name__, exc.message, exc.detail)
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    from app.logging_config import get_logger

    logger = get_logger("errors")
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Something went wrong processing that request.",
            "suggestion": "Check the backend logs (data/logs/clipforge.log) for details. "
            "If this keeps happening, it's a bug -- please report it.",
        },
    )
