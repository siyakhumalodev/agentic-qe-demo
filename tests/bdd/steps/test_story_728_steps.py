"""Step definitions for Story 728 joint-account apportionment scenarios."""

from __future__ import annotations

from decimal import Decimal

from pytest_bdd import given, parsers, scenarios, then

from payout.config import DEPOSIT_LIMIT_GBP
from payout.models import CompensationResult
from payout.money import format_gbp, parse_gbp
from tests.support.scv_builder import ScvBuilder

Results = dict[str, CompensationResult]

scenarios("../features/story_728_joint_accounts.feature")


def _parse_holders(holders: str) -> list[str]:
    return [holder.strip() for holder in holders.split(",")]


@given(
    parsers.parse(
        'a joint account "{account_id}" held in SCV order by eligible depositors "{holders}" '
        "with a balance of £{amount}"
    )
)
def eligible_joint_account(scv: ScvBuilder, account_id: str, holders: str, amount: str) -> None:
    """Build a joint account whose holders are eligible by default."""
    scv.add_joint(account_id, _parse_holders(holders), parse_gbp(amount))


@given(
    parsers.parse(
        'a joint account "{account_id}" held in SCV order by depositors "{holders}" with a balance of £{amount}'
    )
)
def joint_account(scv: ScvBuilder, account_id: str, holders: str, amount: str) -> None:
    """Build a joint account whose holder eligibility may be changed by another step."""
    scv.add_joint(account_id, _parse_holders(holders), parse_gbp(amount))


@given(
    parsers.parse(
        'a joint account "{account_id}" held in SCV order by eligible depositors "{holders}" '
        "that is overdrawn by £{amount}"
    )
)
def overdrawn_joint_account(scv: ScvBuilder, account_id: str, holders: str, amount: str) -> None:
    """Build an overdrawn joint account."""
    scv.add_joint(account_id, _parse_holders(holders), -parse_gbp(amount))


@given(
    parsers.parse(
        'a joint account "{account_id}" held in SCV order by eligible depositors "{holders}" '
        "with each holder's share equal to the deposit limit"
    )
)
def joint_account_at_limit(scv: ScvBuilder, account_id: str, holders: str) -> None:
    """Build a joint account whose equal shares are exactly the configured limit."""
    depositor_ids = _parse_holders(holders)
    scv.add_joint(account_id, depositor_ids, DEPOSIT_LIMIT_GBP * len(depositor_ids))


@given(
    parsers.parse(
        'a joint account "{account_id}" held in SCV order by eligible depositors "{holders}" '
        "with each holder's share £{amount} above the deposit limit"
    )
)
def joint_account_above_limit(scv: ScvBuilder, account_id: str, holders: str, amount: str) -> None:
    """Build a joint account whose equal shares exceed the configured limit."""
    depositor_ids = _parse_holders(holders)
    share = DEPOSIT_LIMIT_GBP + parse_gbp(amount)
    scv.add_joint(account_id, depositor_ids, share * len(depositor_ids))


@then(parsers.parse('depositor "{depositor_id}" is credited £{amount} from account "{account_id}"'))
def depositor_account_credit(
    results: Results,
    depositor_id: str,
    amount: str,
    account_id: str,
) -> None:
    """Assert one depositor's pre-cap credit from an account."""
    actual = results[depositor_id].credited_by_account[account_id]
    expected = parse_gbp(amount)
    assert actual == expected, (
        f"{depositor_id} credit from {account_id} is {format_gbp(actual)}, expected {format_gbp(expected)}"
    )


@then(parsers.parse('depositor "{depositor_id}" has an aggregated balance equal to the deposit limit'))
def aggregate_at_limit(results: Results, depositor_id: str) -> None:
    """Assert a depositor's aggregate equals the configured limit."""
    actual = results[depositor_id].aggregate_balance
    assert actual == DEPOSIT_LIMIT_GBP, (
        f"{depositor_id} aggregate is {format_gbp(actual)}, "
        f"expected the deposit limit {format_gbp(DEPOSIT_LIMIT_GBP)}"
    )


@then(parsers.parse('depositor "{depositor_id}" has an aggregated balance £{amount} above the deposit limit'))
def aggregate_above_limit(results: Results, depositor_id: str, amount: str) -> None:
    """Assert a depositor's aggregate exceeds the configured limit by an offset."""
    actual = results[depositor_id].aggregate_balance
    expected = DEPOSIT_LIMIT_GBP + parse_gbp(amount)
    assert actual == expected, (
        f"{depositor_id} aggregate is {format_gbp(actual)}, expected {format_gbp(expected)} "
        f"({format_gbp(parse_gbp(amount))} above the deposit limit)"
    )


@then(
    parsers.parse(
        'account "{account_id}" credits for depositors "{holders}" are Decimal amounts with 2 decimal places '
        "and total £{amount}"
    )
)
def account_credits_are_exact_and_reconcile(
    results: Results,
    account_id: str,
    holders: str,
    amount: str,
) -> None:
    """Assert joint shares use exact two-place Decimals and reconcile to the account balance."""
    depositor_ids = _parse_holders(holders)
    credits = [results[depositor_id].credited_by_account[account_id] for depositor_id in depositor_ids]

    for depositor_id, credit in zip(depositor_ids, credits, strict=True):
        assert isinstance(credit, Decimal), (
            f"{depositor_id} credit from {account_id} has type {type(credit).__name__}, expected Decimal"
        )
        assert credit.as_tuple().exponent == -2, (
            f"{depositor_id} credit from {account_id} is {credit!r} with exponent {credit.as_tuple().exponent}, "
            "expected exponent -2"
        )

    actual_total = sum(credits, Decimal("0.00"))
    expected_total = parse_gbp(amount)
    assert actual_total == expected_total, (
        f"{account_id} credits total {format_gbp(actual_total)}, expected {format_gbp(expected_total)}"
    )


@then(parsers.parse('depositor "{depositor_id}" has Decimal monetary results with 2 decimal places'))
def depositor_monetary_results_are_exact(results: Results, depositor_id: str) -> None:
    """Assert every monetary result for a depositor is a two-place Decimal."""
    result = results[depositor_id]
    amounts = {
        **result.credited_by_account,
        "aggregate_balance": result.aggregate_balance,
        "compensation": result.compensation,
    }

    for field_name, amount in amounts.items():
        assert isinstance(amount, Decimal), (
            f"{depositor_id} {field_name} has type {type(amount).__name__}, expected Decimal"
        )
        assert amount.as_tuple().exponent == -2, (
            f"{depositor_id} {field_name} is {amount!r} with exponent {amount.as_tuple().exponent}, "
            "expected exponent -2"
        )