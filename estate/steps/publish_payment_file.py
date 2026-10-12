"""PUBLISHING (Python fallback for ``estate/powershell/Publish-PaymentFile.ps1``).

Builds the payment file from the ETL results extract and writes it to the outbound share via a
``.partial`` file and an atomic rename. Same parameters, messages and exit codes as the
PowerShell script: a missing outbound share writes ``Outbound share not found: <path>`` to
stderr and exits 1.

Usage: ``python -m estate.steps.publish_payment_file --run-id RUN-0001 --case-ref CBS-2026-001
--run-date 2026-10-05 --results-file <csv> --outbound-share <dir>``
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
from decimal import Decimal

from estate.payment_file import build_payment_lines, payment_file_name
from estate.steps.common import EXIT_INVALID_DATA, StepError, info, run_step
from payout.money import format_plain

_AMOUNT = re.compile(r"^\d+\.\d{2}$")


def publish(run_id: str, case_ref: str, run_date: str, results_file: str, outbound_share: str) -> None:
    """Write ``PAY_<case_ref>_<run_id>.csv`` to ``outbound_share``."""
    if not os.path.isdir(outbound_share):
        raise StepError(f"Outbound share not found: {outbound_share}")
    if not os.path.isfile(results_file):
        raise StepError(f"Results file not found: {results_file}")

    payments: list[tuple[str, Decimal]] = []
    with open(results_file, "r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            text = (row.get("compensation_gbp") or "").strip()
            if not _AMOUNT.match(text):
                raise StepError(
                    f"Invalid amount '{text}' for depositor {row.get('depositor_id')} in {results_file}",
                    EXIT_INVALID_DATA,
                )
            payments.append((row["depositor_id"], Decimal(text)))

    lines = build_payment_lines(case_ref, run_id, run_date, payments)
    name = payment_file_name(case_ref, run_id)
    count, total = lines[-1].split(",")[1:]
    info(f"Publishing {name}: {count} payment records, total {format_plain(Decimal(total))}")
    target = os.path.join(outbound_share, name)
    partial = f"{target}.partial"
    with open(partial, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    os.replace(partial, target)
    with open(target, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    info(f"Published {name} to {outbound_share} (sha256 {digest})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-ref", required=True)
    parser.add_argument("--run-date", required=True)
    parser.add_argument("--results-file", required=True)
    parser.add_argument("--outbound-share", required=True)
    args = parser.parse_args(argv)
    return run_step(
        lambda: publish(args.run_id, args.case_ref, args.run_date, args.results_file, args.outbound_share)
    )


if __name__ == "__main__":
    sys.exit(main())
