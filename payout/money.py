"""Money helpers: GBP amounts as ``Decimal`` with two decimal places (rule R8)."""

from __future__ import annotations

import re
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from payout.config import MONEY_QUANTUM

ZERO: Decimal = Decimal("0.00")

_GBP_PATTERN = re.compile(
    r"^\s*(?:(?P<minus_before>-)£?|£(?P<minus_after>-)?|)"
    r"(?P<digits>\d{1,3}(?:,\d{3})+|\d+)\.(?P<pence>\d{2})\s*$"
)


def parse_gbp(text: str) -> Decimal:
    """Parse a GBP amount such as ``"£10,000.00"``, ``"10000.00"``, ``"-£250.75"`` or ``"£-250.75"``.

    Exactly two decimal places are required so that amounts in features, files and the UI
    are unambiguous.

    Raises:
        ValueError: if ``text`` is not a valid two-decimal-place amount.
    """
    match = _GBP_PATTERN.match(text)
    if match is None:
        raise ValueError(f"Not a GBP amount with two decimal places: {text!r}")
    negative = bool(match.group("minus_before") or match.group("minus_after"))
    digits = match.group("digits").replace(",", "")
    try:
        value = Decimal(f"{digits}.{match.group('pence')}")
    except InvalidOperation as exc:  # pragma: no cover - the regex already guarantees digits
        raise ValueError(f"Not a GBP amount: {text!r}") from exc
    return -value if negative else value


def to_money(value: Decimal) -> Decimal:
    """Return ``value`` rounded *down* to the penny (never rounds a payment up)."""
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_DOWN)


def format_gbp(value: Decimal) -> str:
    """Format an amount for people, e.g. ``Decimal("1234.5")`` -> ``"£1,234.50"``."""
    amount = value.quantize(MONEY_QUANTUM)
    sign = "-" if amount < 0 else ""
    return f"{sign}£{abs(amount):,.2f}"


def format_plain(value: Decimal) -> str:
    """Format an amount for files and APIs, e.g. ``Decimal("1234.5")`` -> ``"1234.50"``."""
    return f"{value.quantize(MONEY_QUANTUM):.2f}"


def to_pence(value: Decimal) -> int:
    """Convert a two-decimal-place amount to integer pence (exact)."""
    return int((value.quantize(MONEY_QUANTUM) * 100).to_integral_value())


def from_pence(pence: int) -> Decimal:
    """Convert integer pence to a two-decimal-place ``Decimal``."""
    return (Decimal(pence) / 100).quantize(MONEY_QUANTUM)
