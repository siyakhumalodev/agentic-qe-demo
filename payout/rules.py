"""Compensation rules engine.

Simplified rules for demonstration only — not FSCS policy.
The rulebook (R1-R8) is in ``.github/skills/deposit-compensation-rules/SKILL.md``.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from decimal import Decimal
from typing import Iterable

from payout.config import DEPOSIT_LIMIT_GBP
from payout.models import AccountHolding, AccountType, CompensationResult
from payout.money import ZERO, from_pence, to_money, to_pence

logger = logging.getLogger(__name__)


def calculate_compensation(
    holdings: Iterable[AccountHolding],
    limit: Decimal | None = None,
) -> list[CompensationResult]:
    """Calculate compensation after joint apportionment and depositor aggregation (R2-R8).

    Args:
        holdings: SCV rows (one row per account holder).
        limit: deposit protection limit; defaults to ``payout.config.DEPOSIT_LIMIT_GBP`` (R1).

    Returns:
        One result per depositor, in the order depositors first appear in the SCV.
    """
    cap = DEPOSIT_LIMIT_GBP if limit is None else limit
    credited: OrderedDict[str, dict[str, Decimal]] = OrderedDict()
    account_rows: OrderedDict[str, list[AccountHolding]] = OrderedDict()
    names: dict[str, str] = {}
    eligibility: dict[str, bool] = {}

    for holding in holdings:
        names.setdefault(holding.depositor_id, holding.depositor_name)
        # A depositor is eligible only if every SCV row for them says so.
        eligibility[holding.depositor_id] = eligibility.get(holding.depositor_id, True) and holding.depositor_eligible
        credited.setdefault(holding.depositor_id, {})
        account_rows.setdefault(holding.account_id, []).append(holding)

    for rows in account_rows.values():
        if rows[0].account_type is AccountType.JOINT:
            ordered_rows = sorted(rows, key=lambda row: row.holder_seq)
            balance_pence = max(to_pence(rows[0].balance_gbp), 0)  # R6
            share_pence, remainder = divmod(balance_pence, len(ordered_rows))
            allocations = (
                (row, from_pence(share_pence + int(index < remainder)))
                for index, row in enumerate(ordered_rows)
            )
        else:
            allocations = ((row, max(row.balance_gbp, ZERO)) for row in rows)

        for holding, amount in allocations:
            accounts = credited[holding.depositor_id]
            accounts[holding.account_id] = accounts.get(holding.account_id, ZERO) + amount

    results: list[CompensationResult] = []
    for depositor_id, accounts in credited.items():
        aggregate = to_money(sum(accounts.values(), ZERO))  # R2: aggregate before the limit
        eligible = eligibility[depositor_id]
        # R5: an ineligible depositor receives nothing. R7: the cap is inclusive.
        compensation = to_money(min(aggregate, cap)) if eligible else ZERO
        results.append(
            CompensationResult(
                depositor_id=depositor_id,
                depositor_name=names[depositor_id],
                eligible=eligible,
                credited_by_account={account: to_money(amount) for account, amount in accounts.items()},
                aggregate_balance=aggregate,
                compensation=compensation,
            )
        )

    logger.debug("Calculated compensation for %d depositors (limit %s)", len(results), cap)
    return results
