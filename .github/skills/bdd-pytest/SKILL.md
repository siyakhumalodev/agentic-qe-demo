---
name: bdd-pytest
description: Conventions for BDD tests in this repo with pytest-bdd - file layout, tags for traceability (@story_123, @ac_1, @gap_g1), reusable step definitions in tests/bdd/conftest.py, parsers, target_fixture, reading the configured limit, and commands. Use when writing, reviewing or running Gherkin scenarios and step definitions.
---

# BDD with pytest-bdd

## Layout

```
tests/bdd/
  conftest.py                         shared fixtures + step definitions (reuse these first)
  features/<story>_<topic>.feature    Gherkin, e.g. story_123_joint_accounts.feature
  steps/test_<story>_steps.py         scenarios("../features/<file>.feature") + new steps
```

## Tags = traceability

- Feature: `@story_123` (marker for `pytest -m story_123`).
- Scenario: `@ac_1`, `@ac_2` ... for story ACs; `@gap_g1` ... for approved gaps; several tags allowed.
- Scenario names start with the ID: `Scenario: AC1 - A joint account with two holders is split equally`.
- Tags become pytest markers; they are registered in `pytest.ini` (new ones are allowed).

## Steps already available (`tests/bdd/conftest.py`)

| Type | Step text |
|---|---|
| Given | `a sole account "<acc>" for depositor "<dep>" with a balance of £<amount>` |
| Given | `a sole account "<acc>" for depositor "<dep>" with a balance £<amount> above the deposit limit` |
| Given | `a sole account "<acc>" for depositor "<dep>" with a balance equal to the deposit limit` |
| Given | `a sole account "<acc>" for depositor "<dep>" that is overdrawn by £<amount>` |
| Given | `depositor "<dep>" is not eligible for compensation` |
| When | `compensation is calculated` (stores `results`: depositor id -> `CompensationResult`) |
| Then | `depositor "<dep>" is paid £<amount>` / `is paid the deposit limit` |
| Then | `depositor "<dep>" has an aggregated balance of £<amount>` |

`CompensationResult` has `credited_by_account` (account -> amount credited before the cap),
`aggregate_balance`, `compensation`, `eligible`. Build data with the `scv` fixture
(`ScvBuilder`: `add_sole`, `add_joint(account_id, [holders in SCV order], balance)`, `mark_ineligible`).

## Writing new steps

```python
from pytest_bdd import given, parsers, scenarios, then
from payout.config import DEPOSIT_LIMIT_GBP
from payout.money import parse_gbp

scenarios("../features/story_123_joint_accounts.feature")

@given(parsers.parse('a joint account "{account_id}" held by "{holders}" with a balance of £{amount}'))
def joint_account(scv, account_id: str, holders: str, amount: str) -> None:
    scv.add_joint(account_id, [h.strip() for h in holders.split(",")], parse_gbp(amount))
```

- Quote identifiers (`"D9101"`) so patterns cannot overlap; keep each step text unique.
- Amounts: write `£10,000.00` in Gherkin, convert with `parse_gbp` (Decimal, 2 dp).
- **Never hard-code the limit**: phrase it as "the deposit limit" and use `DEPOSIT_LIMIT_GBP`.
- `@when(..., target_fixture="results")` returns values to later steps; no globals.
- Assertion messages state actual vs expected in £ (`format_gbp`).
- Avoid data tables/doc strings unless needed; plain steps read best in a demo.

## Commands

```
pytest tests/bdd -m story_123 -v                        # one story
pytest tests/unit tests/bdd                             # everything deterministic
pytest tests/unit tests/bdd --cov=payout --cov-report=term-missing
```

Red first is fine for a new story - but a scenario must fail on a business assertion, never on
"StepDefinitionNotFound".
