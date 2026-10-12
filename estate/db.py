"""SQLite stores: the control DB (runs, events, steps) and the central payout DB.

Money is stored as integer pence plus a 2 dp text copy, so SQL ``SUM`` is exact.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Sequence

from payout.models import CompensationResult
from payout.money import format_plain, from_pence, to_pence

CONTROL_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT UNIQUE,
    case_ref       TEXT NOT NULL,
    status         TEXT NOT NULL,
    requested_at   TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT,
    failure_reason TEXT,
    payment_file   TEXT,
    deliver_scv    INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS run_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id  TEXT NOT NULL,
    ts      TEXT NOT NULL,
    event   TEXT NOT NULL,
    status  TEXT,
    message TEXT
);
CREATE TABLE IF NOT EXISTS run_steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    step        TEXT NOT NULL,
    command     TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    exit_code   INTEGER,
    stderr_tail TEXT
);
CREATE INDEX IF NOT EXISTS ix_run_events_run ON run_events(run_id);
CREATE INDEX IF NOT EXISTS ix_run_steps_run ON run_steps(run_id);
"""

PAYOUT_SCHEMA = """
CREATE TABLE IF NOT EXISTS payout_results (
    run_id                  TEXT NOT NULL,
    case_ref                TEXT NOT NULL,
    seq                     INTEGER NOT NULL,
    depositor_id            TEXT NOT NULL,
    depositor_name          TEXT NOT NULL,
    eligible                INTEGER NOT NULL,
    aggregate_balance_pence INTEGER NOT NULL,
    compensation_pence      INTEGER NOT NULL,
    compensation_gbp        TEXT NOT NULL,
    PRIMARY KEY (run_id, depositor_id)
);
CREATE TABLE IF NOT EXISTS payout_runs (
    run_id                   TEXT PRIMARY KEY,
    case_ref                 TEXT NOT NULL,
    calculated_at            TEXT NOT NULL,
    depositors               INTEGER NOT NULL,
    payees                   INTEGER NOT NULL,
    total_compensation_pence INTEGER NOT NULL,
    total_compensation_gbp   TEXT NOT NULL
);
"""


class RunStatus(str, Enum):
    """Lifecycle of a payout run."""

    QUEUED = "QUEUED"
    PROVISIONING_VM = "PROVISIONING_VM"
    STAGING_FILES = "STAGING_FILES"
    LOADING_SCV = "LOADING_SCV"
    CALCULATING = "CALCULATING"
    PUBLISHING = "PUBLISHING"
    ARCHIVING = "ARCHIVING"
    DEPROVISIONING_VM = "DEPROVISIONING_VM"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    @property
    def label(self) -> str:
        return STATUS_LABELS[self]

    @property
    def is_terminal(self) -> bool:
        return self in (RunStatus.COMPLETED, RunStatus.FAILED)


STATUS_LABELS: dict[RunStatus, str] = {
    RunStatus.QUEUED: "Queued",
    RunStatus.PROVISIONING_VM: "Provisioning VM",
    RunStatus.STAGING_FILES: "Staging files",
    RunStatus.LOADING_SCV: "Loading SCV",
    RunStatus.CALCULATING: "Calculating",
    RunStatus.PUBLISHING: "Publishing",
    RunStatus.ARCHIVING: "Archiving",
    RunStatus.DEPROVISIONING_VM: "Deprovisioning VM",
    RunStatus.COMPLETED: "Completed",
    RunStatus.FAILED: "Failed",
}

TERMINAL_STATUSES: frozenset[str] = frozenset({RunStatus.COMPLETED.value, RunStatus.FAILED.value})


def now_iso() -> str:
    """Local time with UTC offset, e.g. ``2026-10-05T14:02:01+01:00``."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect(path: Path, *, timeout: float = 15.0) -> sqlite3.Connection:
    """Open a read-write connection in autocommit mode (explicit transactions only)."""
    conn = sqlite3.connect(str(path), timeout=timeout, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` ... ``COMMIT`` (or ``ROLLBACK`` on error)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def ensure_schema(control_db: Path, payout_db: Path) -> None:
    """Create both databases and their tables if they do not exist (idempotent)."""
    control_db.parent.mkdir(parents=True, exist_ok=True)
    for path, schema in ((control_db, CONTROL_SCHEMA), (payout_db, PAYOUT_SCHEMA)):
        conn = connect(path)
        try:
            conn.executescript(schema)
        finally:
            conn.close()


@dataclass
class ControlStore:
    """Data access for the control DB."""

    path: Path

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = connect(self.path)
        try:
            yield conn
        finally:
            conn.close()

    def create_run(self, case_ref: str, *, deliver_scv: bool = True) -> str:
        """Queue a new run and return its id (``RUN-0001``, ``RUN-0002``, ...)."""
        with self._conn() as conn, transaction(conn):
            cursor = conn.execute(
                "INSERT INTO runs (case_ref, status, requested_at, deliver_scv) VALUES (?, ?, ?, ?)",
                (case_ref, RunStatus.QUEUED.value, now_iso(), 1 if deliver_scv else 0),
            )
            row_id = int(cursor.lastrowid or 0)
            run_id = f"RUN-{row_id:04d}"
            conn.execute("UPDATE runs SET run_id = ? WHERE id = ?", (run_id, row_id))
            self._event(conn, run_id, "STATUS", RunStatus.QUEUED, "Payout run requested")
        return run_id

    def claim_next_queued(self) -> str | None:
        """Atomically move the oldest QUEUED run to PROVISIONING_VM and return its id."""
        with self._conn() as conn, transaction(conn):
            row = conn.execute(
                "SELECT run_id FROM runs WHERE status = ? ORDER BY id LIMIT 1", (RunStatus.QUEUED.value,)
            ).fetchone()
            if row is None:
                return None
            run_id = str(row["run_id"])
            conn.execute(
                "UPDATE runs SET status = ?, started_at = ? WHERE run_id = ?",
                (RunStatus.PROVISIONING_VM.value, now_iso(), run_id),
            )
            self._event(conn, run_id, "STATUS", RunStatus.PROVISIONING_VM, "Picked up by the coordinator")
        return run_id

    def set_status(self, run_id: str, status: RunStatus, message: str | None = None) -> None:
        with self._conn() as conn, transaction(conn):
            conn.execute("UPDATE runs SET status = ? WHERE run_id = ?", (status.value, run_id))
            self._event(conn, run_id, "STATUS", status, message or status.label)

    def add_event(self, run_id: str, event: str, message: str) -> None:
        with self._conn() as conn, transaction(conn):
            row = conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            status = RunStatus(row["status"]) if row else None
            self._event(conn, run_id, event, status, message)

    def start_step(self, run_id: str, step: RunStatus, command: str) -> int:
        with self._conn() as conn, transaction(conn):
            cursor = conn.execute(
                "INSERT INTO run_steps (run_id, step, command, started_at) VALUES (?, ?, ?, ?)",
                (run_id, step.value, command, now_iso()),
            )
            return int(cursor.lastrowid or 0)

    def finish_step(self, step_row_id: int, exit_code: int, stderr_tail: str) -> None:
        with self._conn() as conn, transaction(conn):
            conn.execute(
                "UPDATE run_steps SET finished_at = ?, exit_code = ?, stderr_tail = ? WHERE id = ?",
                (now_iso(), exit_code, stderr_tail, step_row_id),
            )

    def complete_run(self, run_id: str, payment_file: str) -> None:
        with self._conn() as conn, transaction(conn):
            conn.execute(
                "UPDATE runs SET status = ?, finished_at = ?, payment_file = ? WHERE run_id = ?",
                (RunStatus.COMPLETED.value, now_iso(), payment_file, run_id),
            )
            self._event(conn, run_id, "STATUS", RunStatus.COMPLETED, "Payout run completed")

    def fail_run(self, run_id: str, reason: str) -> None:
        with self._conn() as conn, transaction(conn):
            conn.execute(
                "UPDATE runs SET status = ?, finished_at = ?, failure_reason = ? WHERE run_id = ?",
                (RunStatus.FAILED.value, now_iso(), reason, run_id),
            )
            self._event(conn, run_id, "STATUS", RunStatus.FAILED, f"Failed: {reason}")

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return _row_to_dict(row) if row else None

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [_row_to_dict(row) for row in rows]

    def events(self, run_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT ts, event, status, message FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def steps(self, run_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT step, command, started_at, finished_at, exit_code, stderr_tail "
                "FROM run_steps WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def counts_by_status(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM runs GROUP BY status").fetchall()
            return {str(row["status"]): int(row["n"]) for row in rows}

    def in_progress_runs(self) -> list[str]:
        """Runs that were picked up but never reached a terminal status."""
        placeholders = ", ".join("?" for _ in TERMINAL_STATUSES)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT run_id FROM runs WHERE status NOT IN ({placeholders}) AND status != ?",
                (*sorted(TERMINAL_STATUSES), RunStatus.QUEUED.value),
            ).fetchall()
            return [str(row["run_id"]) for row in rows]

    def clear(self) -> int:
        """Delete all runs, events and steps (logical reset). Returns the number of runs removed."""
        with self._conn() as conn, transaction(conn):
            count = int(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
            conn.execute("DELETE FROM run_events")
            conn.execute("DELETE FROM run_steps")
            conn.execute("DELETE FROM runs")
        return count

    @staticmethod
    def _event(
        conn: sqlite3.Connection, run_id: str, event: str, status: RunStatus | None, message: str
    ) -> None:
        conn.execute(
            "INSERT INTO run_events (run_id, ts, event, status, message) VALUES (?, ?, ?, ?, ?)",
            (run_id, now_iso(), event, status.value if status else None, message),
        )


@dataclass(frozen=True)
class PayoutSummary:
    """Totals for one run in the payout DB."""

    run_id: str
    depositors: int
    payees: int
    total_compensation: Decimal
    max_payment: Decimal


@dataclass
class PayoutStore:
    """Data access for the central payout DB."""

    path: Path

    def replace_results(self, run_id: str, case_ref: str, results: Sequence[CompensationResult]) -> PayoutSummary:
        """Store the results of a calculation for ``run_id`` (idempotent)."""
        rows = [
            (
                run_id,
                case_ref,
                seq,
                result.depositor_id,
                result.depositor_name,
                1 if result.eligible else 0,
                to_pence(result.aggregate_balance),
                to_pence(result.compensation),
                format_plain(result.compensation),
            )
            for seq, result in enumerate(results, start=1)
        ]
        payees = sum(1 for result in results if result.compensation > 0)
        total_pence = sum(to_pence(result.compensation) for result in results)
        conn = connect(self.path)
        try:
            with transaction(conn):
                conn.execute("DELETE FROM payout_results WHERE run_id = ?", (run_id,))
                conn.execute("DELETE FROM payout_runs WHERE run_id = ?", (run_id,))
                conn.executemany("INSERT INTO payout_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
                conn.execute(
                    "INSERT INTO payout_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (run_id, case_ref, now_iso(), len(rows), payees, total_pence, format_plain(from_pence(total_pence))),
                )
        finally:
            conn.close()
        max_pence = max((to_pence(result.compensation) for result in results), default=0)
        return PayoutSummary(run_id, len(rows), payees, from_pence(total_pence), from_pence(max_pence))

    def summary(self, run_id: str) -> PayoutSummary | None:
        """Totals computed from ``payout_results`` (not from the cached ``payout_runs`` row)."""
        conn = connect(self.path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS depositors, "
                "SUM(CASE WHEN compensation_pence > 0 THEN 1 ELSE 0 END) AS payees, "
                "COALESCE(SUM(compensation_pence), 0) AS total, COALESCE(MAX(compensation_pence), 0) AS max_pence "
                "FROM payout_results WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None or int(row["depositors"]) == 0:
            return None
        return PayoutSummary(
            run_id=run_id,
            depositors=int(row["depositors"]),
            payees=int(row["payees"] or 0),
            total_compensation=from_pence(int(row["total"])),
            max_payment=from_pence(int(row["max_pence"])),
        )

    def payments(self, run_id: str) -> list[dict[str, Any]]:
        conn = connect(self.path)
        try:
            rows = conn.execute(
                "SELECT depositor_id, depositor_name, eligible, compensation_gbp FROM payout_results "
                "WHERE run_id = ? ORDER BY seq",
                (run_id,),
            ).fetchall()
            return [_row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def clear(self) -> None:
        conn = connect(self.path)
        try:
            with transaction(conn):
                conn.execute("DELETE FROM payout_results")
                conn.execute("DELETE FROM payout_runs")
        finally:
            conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}
