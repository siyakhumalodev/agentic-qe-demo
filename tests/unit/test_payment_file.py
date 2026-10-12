"""Payment file format: header, one detail line per payee, reconciling trailer."""

from __future__ import annotations

from decimal import Decimal

import pytest

from estate.payment_file import PaymentFileError, build_payment_lines, parse_payment_file, payment_file_name


def test_file_name_follows_the_convention() -> None:
    assert payment_file_name("CBS-2026-001", "RUN-0007") == "PAY_CBS-2026-001_RUN-0007.csv"


def test_only_depositors_with_compensation_get_a_detail_line() -> None:
    lines = build_payment_lines(
        "CBS-2026-001",
        "RUN-0001",
        "2026-10-05",
        [("D0001", Decimal("5000.00")), ("D0002", Decimal("0.00")), ("D0003", Decimal("0.01"))],
    )
    assert lines == [
        "H,CBS-2026-001,RUN-0001,2026-10-05",
        "D,D0001,5000.00",
        "D,D0003,0.01",
        "T,2,5000.01",
    ]


def test_round_trip_reconciles() -> None:
    text = "\n".join(
        build_payment_lines("CBS-2026-001", "RUN-0002", "2026-10-05",
                            [("D0001", Decimal("120000.00")), ("D0002", Decimal("33.34"))])
    ) + "\n"
    parsed = parse_payment_file(text)
    assert (parsed.case_ref, parsed.run_id, parsed.run_date) == ("CBS-2026-001", "RUN-0002", "2026-10-05")
    assert parsed.trailer_count == len(parsed.details) == 2
    assert parsed.trailer_total == parsed.detail_total == Decimal("120033.34")
    assert parsed.max_amount == Decimal("120000.00")


@pytest.mark.parametrize(
    "text",
    [
        "H,CBS-2026-001,RUN-0001,2026-10-05\n",
        "X,CBS-2026-001,RUN-0001,2026-10-05\nT,0,0.00\n",
        "H,CBS-2026-001,RUN-0001,2026-10-05\nD,D0001,12.5\nT,1,12.50\n",
        "H,CBS-2026-001,RUN-0001,2026-10-05\nD,D0001,12.50\nT,one,12.50\n",
    ],
    ids=["no-trailer", "bad-header", "bad-amount", "bad-count"],
)
def test_malformed_files_are_rejected(text: str) -> None:
    with pytest.raises(PaymentFileError):
        parse_payment_file(text)
