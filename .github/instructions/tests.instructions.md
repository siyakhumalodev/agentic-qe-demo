---
applyTo: "tests/**"
description: Conventions for all tests (unit, BDD, end-to-end).
---

# Test conventions

- **Deterministic.** No `time.sleep`, no fixed waits, no randomness. Wait by polling with a timeout
  (`tests/support/estate_probe.py: wait_until / wait_for_terminal_run`) or Playwright `expect(...)`.
- **Never hard-code the deposit limit** - import `DEPOSIT_LIMIT_GBP` from `payout.config`.
- **Money** is `Decimal` with 2 dp; parse `£` amounts with `payout.money.parse_gbp`.
- **Synthetic data only**: depositor IDs `D0001`..., names "Synthetic Depositor 001"..., fictional firm.
- **Traceability**: BDD scenarios carry `@story_<n>` on the feature and `@ac_<n>` / `@gap_g<n>` per
  scenario; scenario names start with the criterion ID.
- **Layers**: `tests/unit` (pure functions), `tests/bdd` (business rules in Gherkin, steps in
  `tests/bdd/conftest.py` + `tests/bdd/steps/`), `tests/e2e` (`@pytest.mark.e2e`, needs `python -m estate up`).
- **Behind the wall**: end-to-end tests check outcomes through `tests/support/estate_probe.py`
  (control DB, VM lifecycle, shares, payment file, payout DB) - never only the screen.
- **Read-only**: tests change the estate only through the portal UI/API (`start_payout_run`), never
  by writing to its databases or shares.
- **Assertions** carry messages with actual vs expected values. Never weaken, skip or xfail a test to
  get green; a failing test is evidence.
- **Locators**: role, label or `data-testid`; never XPath.
