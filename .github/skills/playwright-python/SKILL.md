---
name: playwright-python
description: How to write and run browser tests for the payout portal with Playwright for Python and pytest-playwright - accessible locators, auto-waiting assertions, base_url, headed/debug runs, tracing, and turning a Playwright MCP exploration into a test. Use when writing, healing or migrating UI tests.
---

# Playwright for Python (pytest-playwright)

## Basics in this repo

- Fixture `page` (pytest-playwright); `base_url = http://localhost:8085` in `pytest.ini`, so `page.goto("/")`.
- Mark browser tests `@pytest.mark.e2e`; run with `pytest tests/e2e -m e2e` (estate must be running).
- Imports: `from playwright.sync_api import Page, expect`.

## Locators - in this order

1. `page.get_by_role("button", name="Start payout run")`
2. `page.get_by_label(...)`, `page.get_by_text(...)` for visible text
3. `page.get_by_test_id("run-status")` - the portal exposes `data-testid` for key values:
   `start-run`, `run-id`, `run-status`, `failure-reason`, `run-summary`, `eligible-depositors-paid`,
   `total-compensation`, `payment-file`, `run-timeline`, `payments-table`, `payment-<depositor_id>`
4. Never XPath or long CSS chains (brittle; the legacy suite's main maintenance cost).

## Waiting

- Assertions auto-wait: `expect(page.get_by_test_id("run-status")).to_have_text("Completed", timeout=120_000)`.
- Wait for either outcome with a regex: `to_have_text(re.compile(r"^(Completed|Failed)$"))`, then assert.
- `expect(page).to_have_url(re.compile(r"/runs/RUN-\d+$"))` after navigation.
- **Never** `time.sleep()` / `page.wait_for_timeout()` in tests. The run page refreshes itself.

## Running and debugging

```text
pytest tests/e2e -m e2e --headed --slowmo 300            # watch it
pytest tests/e2e -m e2e --tracing retain-on-failure      # trace.zip under test-results/
playwright show-trace test-results/<test>/trace.zip
pytest tests/e2e -m e2e --browser-channel msedge         # use installed Edge if Chromium is blocked
```

## From Playwright MCP exploration to a test

1. Explore with the Playwright MCP tools (navigate, snapshot, click) and note the accessible names
   and test ids from the snapshot - not coordinates or generated CSS.
2. Translate each interaction to a locator above and each observation to an `expect(...)`.
3. Add behind-the-UI checks with `tests/support/estate_probe.py` (see the `cross-system-testing` skill).

## Healing UI tests

- Locator broke? Re-snapshot the page, pick the role/label/test-id that matches the intent, keep the assertion.
- Timing issue? Replace waits with `expect(...)` on the state you need. Never add sleeps or widen assertions.
