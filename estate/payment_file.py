"""Payment file format shared by the publisher (Python fallback) and the tests.

```
H,<case_ref>,<run_id>,<YYYY-MM-DD>
D,<depositor_id>,<amount 2dp>        (one line per depositor with compensation > 0)
T,<record_count>,<total 2dp>
```
Lines end with LF; the file is UTF-8 without a BOM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from payout.money import format_plain

_AMOUNT = re.compile(r"^\d+\.\d{2}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PaymentFileError(ValueError):
    """The payment file is malformed."""


@dataclass(frozen=True)
class PaymentLine:
    depositor_id: str
    amount: Decimal


@dataclass(frozen=True)
class PaymentFile:
    """A parsed payment file."""

    case_ref: str
    run_id: str
    run_date: str
    details: tuple[PaymentLine, ...]
    trailer_count: int
    trailer_total: Decimal

    @property
    def detail_total(self) -> Decimal:
        return sum((line.amount for line in self.details), Decimal("0.00"))

    @property
    def max_amount(self) -> Decimal:
        return max((line.amount for line in self.details), default=Decimal("0.00"))


def payment_file_name(case_ref: str, run_id: str) -> str:
    """``PAY_<case_ref>_<run_id>.csv``."""
    return f"PAY_{case_ref}_{run_id}.csv"


def build_payment_lines(
    case_ref: str, run_id: str, run_date: str, payments: Iterable[tuple[str, Decimal]]
) -> list[str]:
    """Build header, detail lines (amount > 0 only, input order) and trailer."""
    details = [(depositor_id, amount) for depositor_id, amount in payments if amount > 0]
    total = sum((amount for _, amount in details), Decimal("0.00"))
    lines = [f"H,{case_ref},{run_id},{run_date}"]
    lines += [f"D,{depositor_id},{format_plain(amount)}" for depositor_id, amount in details]
    lines.append(f"T,{len(details)},{format_plain(total)}")
    return lines


def parse_payment_file(text: str) -> PaymentFile:
    """Parse and structurally validate a payment file (does not reconcile totals)."""
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise PaymentFileError("A payment file needs at least a header and a trailer")
    header = lines[0].split(",")
    if len(header) != 4 or header[0] != "H" or not _DATE.match(header[3]):
        raise PaymentFileError(f"Invalid header line: {lines[0]!r}")
    trailer = lines[-1].split(",")
    if len(trailer) != 3 or trailer[0] != "T" or not trailer[1].isdigit() or not _AMOUNT.match(trailer[2]):
        raise PaymentFileError(f"Invalid trailer line: {lines[-1]!r}")
    details: list[PaymentLine] = []
    for line in lines[1:-1]:
        parts = line.split(",")
        if len(parts) != 3 or parts[0] != "D" or not _AMOUNT.match(parts[2]):
            raise PaymentFileError(f"Invalid detail line: {line!r}")
        details.append(PaymentLine(parts[1], Decimal(parts[2])))
    return PaymentFile(
        case_ref=header[1],
        run_id=header[2],
        run_date=header[3],
        details=tuple(details),
        trailer_count=int(trailer[1]),
        trailer_total=Decimal(trailer[2]),
    )
