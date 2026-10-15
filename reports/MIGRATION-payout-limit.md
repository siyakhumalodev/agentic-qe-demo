---
description: Migration record for the legacy payout-limit UI scenario
---

<!-- markdownlint-disable MD060 -->

# Migration - Payout limit

## Rule conflicts (decision needed)

| Legacy expectation | Rulebook | Source | Proposed |
|--------------------|----------|--------|----------|
| D0002 is paid £85,000.00 | R1 caps an eligible depositor at £120,000.00 from 1 December 2025 | `payout/config.py` (`DEPOSIT_LIMIT_GBP`) and the `deposit-compensation-rules` skill | Assert the configured deposit limit, currently £120,000.00 |

## Construct mapping

| Legacy (SpecFlow + Selenium C#) | Migrated (pytest-bdd + Playwright Python) |
|---------------------------------|-------------------------------------------|
| `[Binding]` and step attributes | pytest-bdd decorators with `parsers.parse` |
| `ScenarioContext` stores the WebDriver | pytest-playwright injects the `page` fixture |
| `ChromeDriver` setup and teardown | pytest-playwright manages the browser lifecycle |
| Absolute XPath and first-row assumption | Case `data-testid` scoped to `case_ref`, then a role-based button locator |
| Fixed `Thread.Sleep` calls and refresh | Playwright assertions auto-wait for navigation and terminal status |
| XPath payment-table traversal | Depositor payment `data-testid` locator |
| Hard-coded £85,000.00 assertion | `DEPOSIT_LIMIT_GBP`, formatted with `format_gbp` |

## Files

* `tests/e2e/features/payout_limit.feature`
* `tests/e2e/test_payout_limit_steps.py`

## Validation

```powershell
.\.venv\Scripts\pytest.exe tests/e2e --collect-only -q
.\.venv\Scripts\pytest.exe tests/e2e/test_payout_limit_steps.py -m e2e -v
```

Collection passed with three e2e tests, including the migrated scenario. The focused migrated test
passed against the running estate in 14.85 seconds. Both commands exited with code 0. pytest-bdd
emitted one upstream `DeprecationWarning` from `gherkin_line.py`; it did not affect collection or
execution.

<!-- markdownlint-enable MD060 -->