"""Deterministic helpers for cross-system tests, built on the shared probe library.

``estate/probe.py`` is the same read-only probe the ``estate`` MCP server exposes to agents, so a
test asserts exactly what an agent observed. Waiting is always *polling with a timeout* - never a
fixed sleep - and every timeout fails with a message that says what was being waited for.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from estate.db import TERMINAL_STATUSES, PayoutSummary
from estate.payment_file import PaymentFile, parse_payment_file
from estate.probe import EstateProbe, ProbeError

__all__ = [
    "CASE_REF",
    "RUN_TIMEOUT_S",
    "EstateProbe",
    "PaymentFile",
    "PayoutSummary",
    "Reconciliation",
    "WaitTimeout",
    "estate_is_running",
    "payout_summary",
    "read_payment_file",
    "start_payout_run",
    "wait_for_terminal_run",
    "wait_until",
]

T = TypeVar("T")

CASE_REF = "CBS-2026-001"
#: Upper bound for one payout run (default speed completes in ~10-15 s). Override with E2E_RUN_TIMEOUT_S.
RUN_TIMEOUT_S: float = float(os.environ.get("E2E_RUN_TIMEOUT_S", "120"))
POLL_INTERVAL_S = 0.25


class WaitTimeout(AssertionError):
    """A condition did not become true before its timeout."""


def wait_until(
    condition: Callable[[], T | None],
    *,
    timeout: float,
    description: str,
    interval: float = POLL_INTERVAL_S,
) -> T:
    """Poll ``condition`` until it returns a truthy value, or fail after ``timeout`` seconds.

    This is the only place the test suite pauses, and only between polls.
    """
    deadline = time.monotonic() + timeout
    last: T | None = None
    while True:
        last = condition()
        if last:
            return last
        if time.monotonic() >= deadline:
            raise WaitTimeout(f"Timed out after {timeout:.0f}s waiting for {description} (last value: {last!r})")
        time.sleep(interval)


def wait_for_terminal_run(probe: EstateProbe, run_id: str, timeout: float = RUN_TIMEOUT_S) -> dict[str, Any]:
    """Wait until the control DB shows ``run_id`` as COMPLETED or FAILED and return the run."""

    def terminal_run() -> dict[str, Any] | None:
        run = probe.get_run(run_id)
        return run if run["status"] in TERMINAL_STATUSES else None

    return wait_until(terminal_run, timeout=timeout, description=f"run {run_id} to finish in the control DB")


def read_payment_file(probe: EstateProbe, run_id: str) -> PaymentFile | None:
    """Parse the payment file for ``run_id`` from the effective outbound share (None if absent)."""
    path = probe.payment_file_path(run_id)
    if not path.is_file():
        return None
    return parse_payment_file(path.read_text(encoding="utf-8"))


def payout_summary(probe: EstateProbe, run_id: str) -> PayoutSummary:
    """Payees, total and largest payment for ``run_id`` from the payout DB."""
    summary = probe.payout_summary(run_id)
    if summary is None:
        raise AssertionError(f"No payout results for {run_id} in the payout DB")
    return summary


def estate_is_running(api_url: str = "http://127.0.0.1:8085") -> bool:
    """True if the estate portal answers its health check."""
    try:
        with urllib.request.urlopen(f"{api_url}/api/health", timeout=2) as response:
            return json.loads(response.read().decode("utf-8")).get("service") == "contoso-payout-estate"
    except (urllib.error.URLError, OSError, ValueError):
        return False


def start_payout_run(
    api_url: str = "http://127.0.0.1:8085", case_ref: str = CASE_REF, *, deliver_scv: bool = True
) -> str:
    """Request a payout run through the portal API (as an operator would) and return its id.

    ``deliver_scv=False`` simulates a missing SCV delivery for negative tests.
    """
    request = urllib.request.Request(
        f"{api_url}/api/runs",
        data=json.dumps({"case_ref": case_ref, "deliver_scv": deliver_scv}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return str(json.loads(response.read().decode("utf-8"))["run_id"])
    except urllib.error.URLError as exc:
        raise ProbeError(f"Could not start a payout run at {api_url}: {exc}") from exc


@dataclass(frozen=True)
class Reconciliation:
    """Payment file vs payout DB, for clear assertion messages."""

    file: PaymentFile
    db: PayoutSummary

    @property
    def problems(self) -> list[str]:
        issues = []
        if self.file.trailer_count != len(self.file.details):
            issues.append(f"trailer count {self.file.trailer_count} != {len(self.file.details)} detail lines")
        if len(self.file.details) != self.db.payees:
            issues.append(f"{len(self.file.details)} detail lines != {self.db.payees} payees in the payout DB")
        if self.file.trailer_total != self.file.detail_total:
            issues.append(f"trailer total {self.file.trailer_total} != sum of detail lines {self.file.detail_total}")
        if self.file.detail_total != self.db.total_compensation:
            issues.append(f"file total {self.file.detail_total} != payout DB total {self.db.total_compensation}")
        return issues
