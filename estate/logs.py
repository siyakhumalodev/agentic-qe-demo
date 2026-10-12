"""Logging set-up shared by the estate processes (one log file per component)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from estate.paths import EstatePaths

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def attach_file_handler(logger_name: str, log_file: Path, level: int = logging.INFO) -> logging.Logger:
    """Attach a UTF-8 file handler to ``logger_name`` once (idempotent)."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(min(logger.level or level, level))
    target = str(log_file.resolve())
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and handler.baseFilename == target:
            return logger
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, mode="a", encoding="utf-8", delay=False)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    handler.setLevel(level)
    logger.addHandler(handler)
    return logger


def attach_console_handler(logger_name: str = "estate", level: int = logging.INFO) -> None:
    """Echo log records to stderr (used by ``python -m estate up``)."""
    logger = logging.getLogger(logger_name)
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    handler.setLevel(level)
    logger.addHandler(handler)
    logger.setLevel(min(logger.level or level, level))


def configure_component(component: str, paths: EstatePaths, logger_name: str | None = None) -> logging.Logger:
    """Log ``logger_name`` (default ``estate.<component>``) to ``runtime/logs/<component>.log``."""
    return attach_file_handler(logger_name or f"estate.{component}", paths.log_file(component))


def truncate_log(log_file: Path, note: str) -> None:
    """Empty a log file in place (safe while another process appends to it) and write ``note``."""
    from estate.db import now_iso  # local import avoids a cycle at start-up

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("w", encoding="utf-8") as handle:
        handle.write(f"{now_iso()} INFO    [estate] {note}\n")


def safe_console_streams() -> None:
    """Never crash on characters the console code page cannot encode (e.g. on Windows)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="backslashreplace", line_buffering=True)
            except (ValueError, OSError):  # pragma: no cover - stream already detached/closed
                pass
