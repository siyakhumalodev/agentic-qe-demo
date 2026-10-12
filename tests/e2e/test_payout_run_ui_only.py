"""Legacy-style UI-only regression test: start a payout run and check that the portal says Completed.

This is what a front-end-only regression pack typically checks. It looks at the screen and nothing
behind it - keep it as a contrast to the cross-system test.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.support.estate_probe import RUN_TIMEOUT_S


@pytest.mark.e2e
def test_payout_run_completes_in_the_portal(page: Page) -> None:
    page.goto("/")
    page.get_by_role("button", name="Start payout run").click()

    expect(page.get_by_role("heading", name="Payout run")).to_be_visible()
    expect(page.get_by_test_id("run-status")).to_have_text("Completed", timeout=RUN_TIMEOUT_S * 1000)
