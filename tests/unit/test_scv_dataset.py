"""The synthetic SCV dataset is valid and covers the edge cases the demo relies on."""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from payout.config import DEPOSIT_LIMIT_GBP
from payout.models import AccountHolding, AccountType
from payout.scv import ScvFormatError, read_scv

DATASET = Path(__file__).resolve().parents[2] / "estate" / "data" / "CBS-2026-001_SCV.csv"
HEADER = "account_id,account_type,holder_seq,depositor_id,depositor_name,depositor_eligible,balance_gbp"


@pytest.fixture(scope="module")
def holdings() -> list[AccountHolding]:
    return read_scv(DATASET)


def test_dataset_is_synthetic(holdings: list[AccountHolding]) -> None:
    depositors = {h.depositor_id for h in holdings}
    accounts = {h.account_id for h in holdings}
    assert 25 <= len(depositors) <= 35
    assert 35 <= len(accounts) <= 45
    for holding in holdings:
        assert re.fullmatch(r"D\d{4}", holding.depositor_id)
        assert re.fullmatch(r"Synthetic Depositor \d{3}", holding.depositor_name)


def test_dataset_covers_the_edge_cases(holdings: list[AccountHolding]) -> None:
    by_account: dict[str, list[AccountHolding]] = defaultdict(list)
    sole_totals: dict[str, Decimal] = defaultdict(Decimal)
    for holding in holdings:
        by_account[holding.account_id].append(holding)
        if holding.account_type is AccountType.SOLE:
            sole_totals[holding.depositor_id] += max(holding.balance_gbp, Decimal("0"))
    joint = {acc: rows for acc, rows in by_account.items() if rows[0].account_type is AccountType.JOINT}

    assert any(len(rows) == 2 for rows in joint.values()), "joint account with two holders"
    assert any(len(rows) >= 3 for rows in joint.values()), "joint account with three holders"
    assert any(int(rows[0].balance_gbp * 100) % len(rows) for rows in joint.values()), "odd-penny joint balance"
    assert any(any(not r.depositor_eligible for r in rows) for rows in joint.values()), "ineligible co-holder"
    assert any(rows[0].balance_gbp < 0 for rows in joint.values()), "overdrawn joint account"
    assert any(rows[0].balance_gbp < 0 for rows in by_account.values() if len(rows) == 1), "overdrawn sole account"
    assert any(total > DEPOSIT_LIMIT_GBP for total in sole_totals.values()), "depositor over the limit"
    assert any(total == DEPOSIT_LIMIT_GBP for total in sole_totals.values()), "depositor exactly at the limit"
    assert any(not h.depositor_eligible for h in holdings), "ineligible depositor"


def test_reader_rejects_an_unexpected_header(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("account,type\nA1,SOLE\n", encoding="utf-8")
    with pytest.raises(ScvFormatError, match="Unexpected SCV header"):
        read_scv(bad)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (["A1,SOLE,1,D1,Synthetic Depositor 001,Y,10.0"], "two decimal places"),
        (["A1,SOLE,1,D1,Synthetic Depositor 001,X,10.00"], "Y or N"),
        (["A1,JOINT,1,D1,Synthetic Depositor 001,Y,10.00", "A1,JOINT,2,D2,Synthetic Depositor 002,Y,11.00"],
         "disagree on the balance"),
        (["A1,SOLE,1,D1,Synthetic Depositor 001,Y,10.00", "A1,SOLE,2,D2,Synthetic Depositor 002,Y,10.00"],
         "exactly one holder"),
    ],
    ids=["balance-format", "eligibility-flag", "joint-balance-mismatch", "sole-with-two-holders"],
)
def test_reader_rejects_invalid_rows(tmp_path: Path, rows: list[str], message: str) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    with pytest.raises(ScvFormatError, match=message):
        read_scv(bad)
