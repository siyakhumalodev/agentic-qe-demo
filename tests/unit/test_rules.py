"""Unit tests for the compensation rules engine (sole accounts) and money helpers.

Simplified rules for demonstration only — not FSCS policy. The limit is always read from
``payout.config.DEPOSIT_LIMIT_GBP``; tests never hard-code it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from payout.config import DEPOSIT_LIMIT_GBP
from payout.models import CompensationResult
from payout.money import format_gbp, from_pence, parse_gbp, to_money, to_pence
from payout.rules import calculate_compensation
from tests.support.scv_builder import ScvBuilder

PENNY = Decimal("0.01")


def calculate(builder: ScvBuilder, limit: Decimal | None = None) -> dict[str, CompensationResult]:
    return {result.depositor_id: result for result in calculate_compensation(builder.holdings(), limit)}


def test_limit_is_configured_once_as_a_two_decimal_place_decimal() -> None:
    assert isinstance(DEPOSIT_LIMIT_GBP, Decimal)
    assert DEPOSIT_LIMIT_GBP.as_tuple().exponent == -2
    assert DEPOSIT_LIMIT_GBP > 0


def test_sole_account_below_the_limit_is_paid_in_full() -> None:
    scv = ScvBuilder()
    scv.add_sole("A1", "D1", Decimal("50000.00"))
    assert calculate(scv)["D1"].compensation == Decimal("50000.00")


def test_sole_account_above_the_limit_is_capped_at_the_configured_limit() -> None:
    scv = ScvBuilder()
    scv.add_sole("A1", "D1", DEPOSIT_LIMIT_GBP + Decimal("30000.00"))
    assert calculate(scv)["D1"].compensation == DEPOSIT_LIMIT_GBP


@pytest.mark.parametrize(
    ("balance_offset", "expected_offset"),
    [(Decimal("0.00"), Decimal("0.00")), (PENNY, Decimal("0.00")), (-PENNY, -PENNY)],
    ids=["exactly-at-limit", "one-penny-over", "one-penny-under"],
)
def test_limit_is_inclusive_at_the_boundary(balance_offset: Decimal, expected_offset: Decimal) -> None:
    scv = ScvBuilder()
    scv.add_sole("A1", "D1", DEPOSIT_LIMIT_GBP + balance_offset)
    assert calculate(scv)["D1"].compensation == DEPOSIT_LIMIT_GBP + expected_offset


def test_sole_balances_are_aggregated_before_the_limit_is_applied() -> None:
    scv = ScvBuilder()
    scv.add_sole("A1", "D1", Decimal("30000.00"))
    scv.add_sole("A2", "D1", Decimal("20000.00"))
    scv.add_sole("A3", "D2", DEPOSIT_LIMIT_GBP - Decimal("1000.00"))
    scv.add_sole("A4", "D2", Decimal("2000.00"))
    results = calculate(scv)
    assert results["D1"].aggregate_balance == Decimal("50000.00")
    assert results["D1"].compensation == Decimal("50000.00")
    assert results["D2"].aggregate_balance == DEPOSIT_LIMIT_GBP + Decimal("1000.00")
    assert results["D2"].compensation == DEPOSIT_LIMIT_GBP


def test_ineligible_depositor_receives_nothing() -> None:
    scv = ScvBuilder()
    scv.add_sole("A1", "D1", Decimal("20000.00"))
    scv.mark_ineligible("D1")
    result = calculate(scv)["D1"]
    assert result.eligible is False
    assert result.compensation == Decimal("0.00")


def test_overdrawn_balance_counts_as_zero() -> None:
    scv = ScvBuilder()
    scv.add_sole("A1", "D1", Decimal("-250.00"))
    scv.add_sole("A2", "D1", Decimal("1000.00"))
    result = calculate(scv)["D1"]
    assert result.credited_by_account["A1"] == Decimal("0.00")
    assert result.compensation == Decimal("1000.00")


def test_results_follow_the_scv_order_of_depositors() -> None:
    scv = ScvBuilder()
    for account, depositor in (("A1", "D3"), ("A2", "D1"), ("A3", "D3"), ("A4", "D2")):
        scv.add_sole(account, depositor, Decimal("10.00"))
    assert [r.depositor_id for r in calculate_compensation(scv.holdings())] == ["D3", "D1", "D2"]


def test_an_explicit_limit_overrides_the_configured_one() -> None:
    scv = ScvBuilder()
    scv.add_sole("A1", "D1", Decimal("100000.00"))
    assert calculate(scv, limit=Decimal("85000.00"))["D1"].compensation == Decimal("85000.00")


def test_every_amount_is_a_two_decimal_place_decimal() -> None:
    scv = ScvBuilder()
    scv.add_sole("A1", "D1", Decimal("12345.67"))
    result = calculate(scv)["D1"]
    for amount in (result.aggregate_balance, result.compensation, *result.credited_by_account.values()):
        assert isinstance(amount, Decimal)
        assert amount.as_tuple().exponent == -2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("£10,000.00", Decimal("10000.00")),
        ("10000.00", Decimal("10000.00")),
        ("£0.01", Decimal("0.01")),
        ("-£250.75", Decimal("-250.75")),
        ("£-250.75", Decimal("-250.75")),
        (" £1,234,567.89 ", Decimal("1234567.89")),
    ],
)
def test_parse_gbp_accepts_two_decimal_place_amounts(text: str, expected: Decimal) -> None:
    assert parse_gbp(text) == expected


@pytest.mark.parametrize("text", ["10", "10.0", "10.000", "£1,00.00", "abc", "", "£ 10.00 GBP"])
def test_parse_gbp_rejects_ambiguous_amounts(text: str) -> None:
    with pytest.raises(ValueError):
        parse_gbp(text)


def test_money_formatting_and_conversions() -> None:
    assert format_gbp(Decimal("1234.5")) == "£1,234.50"
    assert format_gbp(Decimal("-250.75")) == "-£250.75"
    assert to_pence(Decimal("120000.01")) == 12_000_001
    assert from_pence(12_000_001) == Decimal("120000.01")
    assert to_money(Decimal("33.3333")) == Decimal("33.33")
    assert to_money(Decimal("33.339")) == Decimal("33.33")
