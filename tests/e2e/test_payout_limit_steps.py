"""Migrated payout-limit UI scenario using pytest-bdd and Playwright."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect
from pytest_bdd import given, parsers, scenarios, then, when

from payout.config import DEPOSIT_LIMIT_GBP
from payout.money import format_gbp
from tests.support.estate_probe import RUN_TIMEOUT_S

scenarios("features/payout_limit.feature")


@given("I have opened the payout portal")
def open_payout_portal(page: Page) -> None:
    """Open the payout portal cases page."""
    page.goto("/")


@when(parsers.parse('I start a payout run for case "{case_ref}"'))
def start_payout_run(page: Page, case_ref: str) -> None:
    """Start the payout run for the case named by the scenario."""
    case_row = page.get_by_test_id(f"case-{case_ref}")
    case_row.get_by_role("button", name="Start payout run").click()
    expect(page).to_have_url(re.compile(r"/runs/RUN-\d+$"))


@when("I wait for the payout run to finish")
def wait_for_payout_run(page: Page) -> None:
    """Wait for the run to reach a terminal state without a fixed delay."""
    expect(page.get_by_test_id("run-status")).to_have_text(
        re.compile(r"^(Completed|Failed)$"),
        timeout=RUN_TIMEOUT_S * 1000,
    )


@then(parsers.parse('the run status should be "{expected_status}"'))
def assert_run_status(page: Page, expected_status: str) -> None:
    """Assert the terminal status displayed by the portal."""
    expect(page.get_by_test_id("run-status")).to_have_text(expected_status)


@then(parsers.parse('the payment for depositor "{depositor_id}" should be the deposit limit'))
def assert_payment_is_deposit_limit(page: Page, depositor_id: str) -> None:
    """Assert rule R1 using the configured deposit limit."""
    expect(page.get_by_test_id(f"payment-{depositor_id}")).to_have_text(format_gbp(DEPOSIT_LIMIT_GBP))