"""Configuration for the compensation rules (rule R1 of the rulebook).

Simplified rules for demonstration only — not FSCS policy.

``DEPOSIT_LIMIT_GBP`` is the single source of truth for the deposit protection limit.
Tests and code must read it from here and never hard-code the amount.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

#: Maximum compensation per eligible depositor per authorised firm (R1).
#: £120,000.00 from 1 December 2025 (it was £85,000.00 from 1 January 2017 to 30 November 2025).
DEPOSIT_LIMIT_GBP: Final[Decimal] = Decimal("120000.00")

#: All money is GBP with two decimal places (R8).
CURRENCY: Final[str] = "GBP"
MONEY_QUANTUM: Final[Decimal] = Decimal("0.01")
