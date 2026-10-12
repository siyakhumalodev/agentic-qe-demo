"""LOADING_SCV and CALCULATING: the ETL step (a stand-in for an SSIS package).

* ``load``: load the staged SCV file into the VM's ``staging.db``.
* ``calculate``: read ``staging.db``, apply ``payout.rules.calculate_compensation``, write the
  results to the VM's ``work.db`` and to the central ``payout.db``, and write the results extract
  (``payout_results.csv``) that the publish step turns into the payment file.

Usage:
``python -m estate.steps.etl load --run-id RUN-0001 --vm-dir <dir> --scv-file <csv>``
``python -m estate.steps.etl calculate --run-id RUN-0001 --vm-dir <dir> --case-ref CBS-2026-001
--payout-db <db> --extract-file <csv>``
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sqlite3
import sys
from pathlib import Path

from estate.db import PayoutStore, now_iso
from estate.logs import configure_component
from estate.paths import EstatePaths
from estate.steps.common import EXIT_INVALID_DATA, StepError, info, run_step
from payout.money import format_plain
from payout.rules import calculate_compensation
from payout.scv import SCV_COLUMNS, ScvFormatError, parse_scv_rows, read_scv

logger = logging.getLogger("estate.etl")


def load(run_id: str, vm_dir: Path, scv_file: Path) -> int:
    """Load the SCV into ``staging.db``. Returns the number of rows loaded."""
    staging_db = _require_vm_database(vm_dir, "staging.db")
    if not scv_file.is_file():
        raise StepError(f"SCV file not found: {scv_file}")
    try:
        holdings = read_scv(scv_file)
    except ScvFormatError as exc:
        raise StepError(f"Invalid SCV file {scv_file.name}: {exc}", EXIT_INVALID_DATA) from exc
    conn = sqlite3.connect(str(staging_db))
    try:
        with conn:
            conn.execute("DELETE FROM scv_staging")
            conn.executemany(
                "INSERT INTO scv_staging (account_id, account_type, holder_seq, depositor_id, depositor_name, "
                "depositor_eligible, balance_gbp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        h.account_id,
                        h.account_type.value,
                        h.holder_seq,
                        h.depositor_id,
                        h.depositor_name,
                        "Y" if h.depositor_eligible else "N",
                        format_plain(h.balance_gbp),
                    )
                    for h in holdings
                ],
            )
    finally:
        conn.close()
    accounts = len({h.account_id for h in holdings})
    depositors = len({h.depositor_id for h in holdings})
    _audit(vm_dir, "load", f"{len(holdings)} rows, {accounts} accounts, {depositors} depositors")
    logger.info("%s load: %d SCV rows (%d accounts, %d depositors) loaded into %s", run_id, len(holdings),
                accounts, depositors, staging_db)
    info(f"Loaded {len(holdings)} SCV rows ({accounts} accounts, {depositors} depositors) into staging.db")
    return len(holdings)


def calculate(run_id: str, vm_dir: Path, case_ref: str, payout_db: Path, extract_file: Path) -> None:
    """Calculate compensation and write work.db, payout.db and the results extract."""
    staging_db = _require_vm_database(vm_dir, "staging.db")
    work_db = _require_vm_database(vm_dir, "work.db")
    conn = sqlite3.connect(str(staging_db))
    conn.row_factory = sqlite3.Row
    try:
        rows = [
            {column: str(row[column]) for column in SCV_COLUMNS}
            for row in conn.execute(f"SELECT {', '.join(SCV_COLUMNS)} FROM scv_staging ORDER BY row_no")
        ]
    finally:
        conn.close()
    if not rows:
        raise StepError(f"No SCV rows in {staging_db}; was the load step successful?", EXIT_INVALID_DATA)
    try:
        holdings = parse_scv_rows(rows)
    except ScvFormatError as exc:
        raise StepError(f"Invalid staged SCV data: {exc}", EXIT_INVALID_DATA) from exc

    results = calculate_compensation(holdings)

    work = sqlite3.connect(str(work_db))
    try:
        with work:
            work.execute("DELETE FROM calc_results")
            work.executemany(
                "INSERT INTO calc_results VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (seq, r.depositor_id, r.depositor_name, 1 if r.eligible else 0,
                     format_plain(r.aggregate_balance), format_plain(r.compensation))
                    for seq, r in enumerate(results, start=1)
                ],
            )
    finally:
        work.close()

    summary = PayoutStore(payout_db).replace_results(run_id, case_ref, results)

    extract_file.parent.mkdir(parents=True, exist_ok=True)
    temp = extract_file.with_name(extract_file.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["depositor_id", "compensation_gbp"])
        for result in results:
            writer.writerow([result.depositor_id, format_plain(result.compensation)])
    os.replace(temp, extract_file)

    message = (f"{summary.depositors} depositors, {summary.payees} payees, total "
               f"{format_plain(summary.total_compensation)}, largest payment {format_plain(summary.max_payment)}")
    _audit(vm_dir, "calculate", message)
    logger.info("%s calculate: %s; results written to payout.db and %s", run_id, message, extract_file.name)
    info(f"Calculated compensation: {message}")


def _require_vm_database(vm_dir: Path, name: str) -> Path:
    database = vm_dir / name
    if not database.is_file():
        raise StepError(f"VM database not found: {database} (was the VM provisioned?)")
    return database


def _audit(vm_dir: Path, phase: str, message: str) -> None:
    conn = sqlite3.connect(str(vm_dir / "work.db"))
    try:
        with conn:
            conn.execute("INSERT INTO etl_audit (ts, phase, message) VALUES (?, ?, ?)", (now_iso(), phase, message))
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)
    load_cmd = sub.add_parser("load")
    load_cmd.add_argument("--run-id", required=True)
    load_cmd.add_argument("--vm-dir", required=True, type=Path)
    load_cmd.add_argument("--scv-file", required=True, type=Path)
    calc_cmd = sub.add_parser("calculate")
    calc_cmd.add_argument("--run-id", required=True)
    calc_cmd.add_argument("--vm-dir", required=True, type=Path)
    calc_cmd.add_argument("--case-ref", required=True)
    calc_cmd.add_argument("--payout-db", required=True, type=Path)
    calc_cmd.add_argument("--extract-file", required=True, type=Path)
    args = parser.parse_args(argv)

    configure_component("etl", EstatePaths.from_env())

    def body() -> None:
        if args.phase == "load":
            load(args.run_id, args.vm_dir, args.scv_file)
        else:
            calculate(args.run_id, args.vm_dir, args.case_ref, args.payout_db, args.extract_file)

    exit_code = run_step(body)
    if exit_code:
        logger.error("%s %s failed with exit code %d", args.run_id, args.phase, exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
