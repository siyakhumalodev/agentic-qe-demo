"""ARCHIVING: move everything in ``<processing-share>/<run-id>/`` to ``<archive-share>/<run-id>/``.

Usage: ``python -m estate.steps.archive --run-id RUN-0001 --processing-share <dir> --archive-share <dir>``
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from estate.steps.common import StepError, info, run_step


def archive(run_id: str, processing_share: Path, archive_share: Path) -> None:
    source = processing_share / run_id
    if not source.is_dir():
        raise StepError(f"Nothing to archive: {source} not found")
    target = archive_share / run_id
    target.mkdir(parents=True, exist_ok=True)
    moved = []
    for item in sorted(source.iterdir()):
        shutil.move(str(item), str(target / item.name))
        moved.append(item.name)
    source.rmdir()
    info(f"Archived {len(moved)} file(s) to {target}: {', '.join(moved)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--processing-share", required=True, type=Path)
    parser.add_argument("--archive-share", required=True, type=Path)
    args = parser.parse_args(argv)
    return run_step(lambda: archive(args.run_id, args.processing_share, args.archive_share))


if __name__ == "__main__":
    sys.exit(main())
