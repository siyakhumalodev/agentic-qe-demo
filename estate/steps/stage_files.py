"""STAGING_FILES (Python fallback for ``estate/powershell/Move-ScvFiles.ps1``).

Moves the SCV file from the inbound share to ``<processing-share>/<run-id>/``.
Same parameters, messages and exit codes as the PowerShell script.

Usage: ``python -m estate.steps.stage_files --run-id RUN-0001 --inbound-share <dir>
--processing-share <dir> --file-name CBS-2026-001_SCV.csv``
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

from estate.steps.common import StepError, info, run_step


def stage(run_id: str, inbound_share: str, processing_share: str, file_name: str) -> None:
    """Move ``file_name`` from the inbound share into the run's processing folder."""
    if not os.path.isdir(inbound_share):
        raise StepError(f"Inbound share not found: {inbound_share}")
    source = os.path.join(inbound_share, file_name)
    if not os.path.isfile(source):
        raise StepError(f"SCV file not found: {source}")
    target = os.path.join(processing_share, run_id)
    os.makedirs(target, exist_ok=True)
    destination = os.path.join(target, file_name)
    if os.path.isfile(destination):
        os.remove(destination)
    shutil.move(source, destination)
    info(f"Moved {file_name} to {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inbound-share", required=True)
    parser.add_argument("--processing-share", required=True)
    parser.add_argument("--file-name", required=True)
    args = parser.parse_args(argv)
    return run_step(lambda: stage(args.run_id, args.inbound_share, args.processing_share, args.file_name))


if __name__ == "__main__":
    sys.exit(main())
