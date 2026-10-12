"""Builds synthetic SCV holdings for scenarios and unit tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Sequence

from payout.models import AccountHolding, AccountType


@dataclass
class ScvBuilder:
    """Collects accounts in SCV order, then materialises ``AccountHolding`` rows.

    Eligibility is applied when ``holdings()`` is called, so a step such as
    "depositor D9110 is not eligible" can come after the accounts are defined.
    """

    _accounts: list[tuple[str, AccountType, tuple[str, ...], Decimal]] = field(default_factory=list)
    _ineligible: set[str] = field(default_factory=set)

    def add_sole(self, account_id: str, depositor_id: str, balance: Decimal) -> None:
        self._accounts.append((account_id, AccountType.SOLE, (depositor_id,), balance))

    def add_joint(self, account_id: str, depositor_ids: Sequence[str], balance: Decimal) -> None:
        holders = tuple(depositor_ids)
        if len(holders) < 2:
            raise ValueError(f"A joint account needs at least two holders, got {holders}")
        self._accounts.append((account_id, AccountType.JOINT, holders, balance))

    def mark_ineligible(self, depositor_id: str) -> None:
        self._ineligible.add(depositor_id)

    def holdings(self) -> list[AccountHolding]:
        return [
            AccountHolding(
                account_id=account_id,
                account_type=account_type,
                holder_seq=seq,
                depositor_id=depositor_id,
                depositor_name=f"Synthetic Depositor {depositor_id.lstrip('D')}",
                depositor_eligible=depositor_id not in self._ineligible,
                balance_gbp=balance,
            )
            for account_id, account_type, holders, balance in self._accounts
            for seq, depositor_id in enumerate(holders, start=1)
        ]
