"""Shared pytest-bdd fixtures and step definitions for the compensation rules.

Simplified rules for demonstration only — not FSCS policy.

Conventions (see .github/skills/bdd-pytest/SKILL.md):
* amounts in steps are written like ``£10,000.00`` and parsed with ``payout.money.parse_gbp``;
* anything that depends on the limit says "the deposit limit" and reads
  ``payout.config.DEPOSIT_LIMIT_GBP`` - never a hard-coded amount;
* steps here are shared by every feature under ``tests/bdd``; story-specific steps live in
  ``tests/bdd/steps/test_<story>_steps.py``.
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, then, when

from payout.config import DEPOSIT_LIMIT_GBP
from payout.models import CompensationResult
from payout.money import format_gbp, parse_gbp
from payout.rules import calculate_compensation
from tests.support.scv_builder import ScvBuilder

Results = dict[str, CompensationResult]


@pytest.fixture
def scv() -> ScvBuilder:
    """The SCV under construction for one scenario."""
    return ScvBuilder()


# -- Given -------------------------------------------------------------------------------------


@given(parsers.parse('a sole account "{account_id}" for depositor "{depositor_id}" with a balance of £{amount}'))
def sole_account(scv: ScvBuilder, account_id: str, depositor_id: str, amount: str) -> None:
    scv.add_sole(account_id, depositor_id, parse_gbp(amount))


@given(
    parsers.parse(
        'a sole account "{account_id}" for depositor "{depositor_id}" with a balance £{amount} above the deposit limit'
    )
)
def sole_account_above_limit(scv: ScvBuilder, account_id: str, depositor_id: str, amount: str) -> None:
    scv.add_sole(account_id, depositor_id, DEPOSIT_LIMIT_GBP + parse_gbp(amount))


@given(parsers.parse('a sole account "{account_id}" for depositor "{depositor_id}" with a balance equal to the deposit limit'))
def sole_account_at_limit(scv: ScvBuilder, account_id: str, depositor_id: str) -> None:
    scv.add_sole(account_id, depositor_id, DEPOSIT_LIMIT_GBP)


@given(parsers.parse('a sole account "{account_id}" for depositor "{depositor_id}" that is overdrawn by £{amount}'))
def overdrawn_sole_account(scv: ScvBuilder, account_id: str, depositor_id: str, amount: str) -> None:
    scv.add_sole(account_id, depositor_id, -parse_gbp(amount))


@given(parsers.parse('depositor "{depositor_id}" is not eligible for compensation'))
def ineligible_depositor(scv: ScvBuilder, depositor_id: str) -> None:
    scv.mark_ineligible(depositor_id)


# -- When --------------------------------------------------------------------------------------


@when("compensation is calculated", target_fixture="results")
def compensation_is_calculated(scv: ScvBuilder) -> Results:
    return {result.depositor_id: result for result in calculate_compensation(scv.holdings())}


# -- Then --------------------------------------------------------------------------------------


@then(parsers.parse('depositor "{depositor_id}" is paid £{amount}'))
def depositor_is_paid(results: Results, depositor_id: str, amount: str) -> None:
    actual = results[depositor_id].compensation
    assert actual == parse_gbp(amount), f"{depositor_id} is paid {format_gbp(actual)}, expected £{amount}"


@then(parsers.parse('depositor "{depositor_id}" is paid the deposit limit'))
def depositor_is_paid_the_limit(results: Results, depositor_id: str) -> None:
    actual = results[depositor_id].compensation
    assert actual == DEPOSIT_LIMIT_GBP, (
        f"{depositor_id} is paid {format_gbp(actual)}, expected the deposit limit {format_gbp(DEPOSIT_LIMIT_GBP)}"
    )


@then(parsers.parse('depositor "{depositor_id}" has an aggregated balance of £{amount}'))
def aggregated_balance(results: Results, depositor_id: str, amount: str) -> None:
    actual = results[depositor_id].aggregate_balance
    assert actual == parse_gbp(amount), f"{depositor_id} aggregate is {format_gbp(actual)}, expected £{amount}"
