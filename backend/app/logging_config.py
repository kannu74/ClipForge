"""
Structured logging setup. Import `get_logger(__name__)` anywhere instead of
using print(). Logs go to stdout (for `uvicorn --reload` visibility) and to
a rotating file under data/logs/clipforge.log.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def configure_logging(log_dir: Path, level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger("clipforge")
    root.setLevel(level.upper())
    root.propagate = False

    # Windows consoles default to a legacy code page; never let a Hindi /
    # Devanagari log line raise an encoding error.
    try:
        sys.stdout.reconfigure(errors="replace")  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        pass
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    root.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        log_dir / "clipforge.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"clipforge.{name}")
