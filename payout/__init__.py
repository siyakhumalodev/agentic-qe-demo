"""Deposit compensation calculation for the fictional Contoso Building Society payout.

Simplified rules for demonstration only — not FSCS policy.
The rulebook lives in ``.github/skills/deposit-compensation-rules/SKILL.md``.
"""

from payout.config import DEPOSIT_LIMIT_GBP
from payout.models import AccountHolding, AccountType, CompensationResult
from payout.rules import calculate_compensation

__all__ = [
    "DEPOSIT_LIMIT_GBP",
    "AccountHolding",
    "AccountType",
    "CompensationResult",
    "calculate_compensation",
]
