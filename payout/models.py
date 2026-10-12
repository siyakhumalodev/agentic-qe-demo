"""Domain model for the Single Customer View (SCV) and compensation results."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Mapping


class AccountType(str, Enum):
    """Account ownership as recorded in the SCV file."""

    SOLE = "SOLE"
    JOINT = "JOINT"


@dataclass(frozen=True)
class AccountHolding:
    """One SCV row: one holder of one account.

    For joint accounts the SCV repeats the *full* account balance on every holder row;
    ``holder_seq`` gives the order of the holders on the account (1, 2, 3, ...).
    """

    account_id: str
    account_type: AccountType
    holder_seq: int
    depositor_id: str
    depositor_name: str
    depositor_eligible: bool
    balance_gbp: Decimal


@dataclass(frozen=True)
class CompensationResult:
    """Compensation outcome for one depositor.

    Attributes:
        credited_by_account: amount credited to this depositor from each account
            (after any apportionment) before the limit is applied.
        aggregate_balance: sum of ``credited_by_account`` (R2).
        compensation: amount payable after eligibility (R5) and the limit (R7).
    """

    depositor_id: str
    depositor_name: str
    eligible: bool
    credited_by_account: Mapping[str, Decimal] = field(default_factory=dict)
    aggregate_balance: Decimal = Decimal("0.00")
    compensation: Decimal = Decimal("0.00")
