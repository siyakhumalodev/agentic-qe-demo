"""Helpers shared by the step processes."""

from __future__ import annotations

import os
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import Any, Callable

EXIT_OK = 0
EXIT_PRECONDITION = 1
EXIT_INVALID_DATA = 2
EXIT_UNEXPECTED = 3


class StepError(Exception):
    """A step failed in an expected way; the message goes to stderr unchanged."""

    def __init__(self, message: str, exit_code: int = EXIT_PRECONDITION) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def info(message: str) -> None:
    """Write a progress line to stdout (captured into ``runtime/logs/steps.log``)."""
    print(message, flush=True)


def run_step(body: Callable[[], None]) -> int:
    """Run ``body`` and translate failures into the shared exit codes."""
    try:
        body()
    except StepError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 - a step must always exit with a code, never a traceback
        print(f"Unexpected error: {exc}", file=sys.stderr, flush=True)
        return EXIT_UNEXPECTED
    return EXIT_OK


def rmtree_robust(path: Path, attempts: int = 10) -> None:
    """Delete a folder tree, retrying briefly (Windows: antivirus or indexer handles)."""

    def _make_writable(func: Callable[..., Any], target: str, *_: Any) -> None:
        os.chmod(target, stat.S_IWRITE)
        func(target)

    for attempt in range(attempts):
        if not path.exists():
            return
        try:
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=_make_writable)
            else:  # pragma: no cover - Python 3.11
                shutil.rmtree(path, onerror=_make_writable)
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.1 * (attempt + 1))
