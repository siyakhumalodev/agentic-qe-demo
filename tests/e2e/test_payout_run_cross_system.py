"""Cross-system regression test for the CBS-2026-001 payout journey."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from payout.config import DEPOSIT_LIMIT_GBP
from payout.money import parse_gbp
from tests.support.estate_probe import (
    CASE_REF,
    RUN_TIMEOUT_S,
    EstateProbe,
    Reconciliation,
    payout_summary,
    read_payment_file,
    wait_for_terminal_run,
)


@pytest.mark.e2e
def test_payout_run_reconciles_across_the_estate(page: Page, probe: EstateProbe) -> None:
    """A completed portal run must reconcile with its VM, shares, file and payout DB."""
    page.goto("/")
    page.get_by_role("button", name="Start payout run").click()

    expect(page).to_have_url(re.compile(r"/runs/RUN-\d+$"))
    run_id = page.get_by_test_id("run-id").inner_text()
    status = page.get_by_test_id("run-status")
    expect(status).to_have_text(re.compile(r"^(Completed|Failed)$"), timeout=RUN_TIMEOUT_S * 1000)
    assert status.inner_text() == "Completed", f"UI status for {run_id} was {status.inner_text()!r}, expected 'Completed'"

    ui_payees = int(page.get_by_test_id("eligible-depositors-paid").inner_text())
    ui_total = parse_gbp(page.get_by_test_id("total-compensation").inner_text())
    ui_payment_file = page.get_by_test_id("payment-file").inner_text()

    run = wait_for_terminal_run(probe, run_id)
    assert run["status"] == "COMPLETED", (
        f"Control DB status for {run_id} was {run['status']!r}, expected 'COMPLETED'; "
        f"failure reason: {run['failure_reason']!r}"
    )
    failed_steps = [step for step in run["steps"] if step["exit_code"] != 0]
    assert not failed_steps, f"Steps with non-zero exit codes for {run_id}: {failed_steps}"

    event_names = [event["event"] for event in run["events"]]
    assert "VM_PROVISIONED" in event_names, f"VM_PROVISIONED event missing for {run_id}: {event_names}"
    assert "VM_DEPROVISIONED" in event_names, f"VM_DEPROVISIONED event missing for {run_id}: {event_names}"
    assert event_names.index("VM_PROVISIONED") < event_names.index("VM_DEPROVISIONED"), (
        f"VM lifecycle events are out of order for {run_id}: {event_names}"
    )
    assert not run["vm"]["present"], f"VM folder still exists after {run_id}: {run['vm']['path']}"

    archive_names = {item["name"] for item in probe.list_share("archive")["files"]}
    archived_scv = f"{run_id}/{CASE_REF}_SCV.csv"
    assert archived_scv in archive_names, f"SCV not archived for {run_id}; archive contains: {sorted(archive_names)}"

    payment_file = read_payment_file(probe, run_id)
    assert payment_file is not None, (
        f"Payment file not published for {run_id} to effective outbound path {probe.payment_file_path(run_id)}"
    )
    assert payment_file.case_ref == CASE_REF, (
        f"Payment file case was {payment_file.case_ref!r}, expected {CASE_REF!r}"
    )
    assert payment_file.run_id == run_id, f"Payment file run was {payment_file.run_id!r}, expected {run_id!r}"
    assert ui_payment_file == run["payment_file"] == probe.payment_file_path(run_id).name, (
        f"Payment filename mismatch for {run_id}: UI={ui_payment_file!r}, "
        f"control DB={run['payment_file']!r}, effective path={probe.payment_file_path(run_id).name!r}"
    )

    db_summary = payout_summary(probe, run_id)
    reconciliation = Reconciliation(payment_file, db_summary)
    assert not reconciliation.problems, f"Payment reconciliation failed for {run_id}: {reconciliation.problems}"
    assert ui_payees == db_summary.payees, (
        f"UI payees {ui_payees} != payout DB payees {db_summary.payees} for {run_id}"
    )
    assert ui_total == payment_file.trailer_total == db_summary.total_compensation, (
        f"Total mismatch for {run_id}: UI={ui_total}, file={payment_file.trailer_total}, "
        f"payout DB={db_summary.total_compensation}"
    )
    assert payment_file.max_amount <= DEPOSIT_LIMIT_GBP, (
        f"Payment file maximum {payment_file.max_amount} exceeds configured limit {DEPOSIT_LIMIT_GBP} for {run_id}"
    )
    assert db_summary.max_payment <= DEPOSIT_LIMIT_GBP, (
        f"Payout DB maximum {db_summary.max_payment} exceeds configured limit {DEPOSIT_LIMIT_GBP} for {run_id}"
    )