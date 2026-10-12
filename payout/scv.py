"""Reading and validating Single Customer View (SCV) files.

SCV CSV columns (one row per account holder; the balance is repeated on each holder row):
``account_id,account_type,holder_seq,depositor_id,depositor_name,depositor_eligible,balance_gbp``
"""

from __future__ import annotations

import csv
import re
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

from payout.models import AccountHolding, AccountType

SCV_COLUMNS: tuple[str, ...] = (
    "account_id",
    "account_type",
    "holder_seq",
    "depositor_id",
    "depositor_name",
    "depositor_eligible",
    "balance_gbp",
)

_BALANCE = re.compile(r"^-?\d+\.\d{2}$")
_ELIGIBLE = {"Y": True, "N": False}


class ScvFormatError(ValueError):
    """The SCV file does not match the expected format."""


def parse_scv_rows(rows: Iterable[Mapping[str, str]]) -> list[AccountHolding]:
    """Convert raw SCV rows (``csv.DictReader`` style) into validated holdings.

    Raises:
        ScvFormatError: with the 1-based data row number of the first invalid row.
    """
    holdings: list[AccountHolding] = []
    for row_no, row in enumerate(rows, start=1):
        try:
            account_type = AccountType(row["account_type"].strip().upper())
            holder_seq = int(row["holder_seq"])
            eligible_flag = row["depositor_eligible"].strip().upper()
            balance_text = row["balance_gbp"].strip()
            if eligible_flag not in _ELIGIBLE:
                raise ScvFormatError(f"depositor_eligible must be Y or N, got {eligible_flag!r}")
            if not _BALANCE.match(balance_text):
                raise ScvFormatError(f"balance_gbp must have exactly two decimal places, got {balance_text!r}")
            if holder_seq < 1:
                raise ScvFormatError(f"holder_seq must be 1 or more, got {holder_seq}")
            holdings.append(
                AccountHolding(
                    account_id=row["account_id"].strip(),
                    account_type=account_type,
                    holder_seq=holder_seq,
                    depositor_id=row["depositor_id"].strip(),
                    depositor_name=row["depositor_name"].strip(),
                    depositor_eligible=_ELIGIBLE[eligible_flag],
                    balance_gbp=Decimal(balance_text),
                )
            )
        except ScvFormatError as exc:
            raise ScvFormatError(f"SCV row {row_no}: {exc}") from exc
        except (KeyError, ValueError, AttributeError) as exc:
            raise ScvFormatError(f"SCV row {row_no}: invalid value ({exc})") from exc
    _check_accounts(holdings)
    return holdings


def read_scv(path: Path) -> list[AccountHolding]:
    """Read and validate an SCV CSV file."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = tuple(reader.fieldnames or ())
        if header != SCV_COLUMNS:
            raise ScvFormatError(f"Unexpected SCV header {header}; expected {SCV_COLUMNS}")
        return parse_scv_rows(reader)


def _check_accounts(holdings: list[AccountHolding]) -> None:
    """Cross-row checks: consistent balances, unique holder sequence, sole accounts have one holder."""
    seen: dict[str, list[AccountHolding]] = {}
    for holding in holdings:
        seen.setdefault(holding.account_id, []).append(holding)
    for account_id, rows in seen.items():
        if len({row.balance_gbp for row in rows}) != 1:
            raise ScvFormatError(f"Account {account_id}: holder rows disagree on the balance")
        if len({row.holder_seq for row in rows}) != len(rows):
            raise ScvFormatError(f"Account {account_id}: duplicate holder_seq")
        if rows[0].account_type is AccountType.SOLE and len(rows) != 1:
            raise ScvFormatError(f"Account {account_id}: a SOLE account must have exactly one holder")
        if len({row.account_type for row in rows}) != 1:
            raise ScvFormatError(f"Account {account_id}: holder rows disagree on the account type")
