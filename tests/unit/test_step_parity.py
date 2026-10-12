"""The two PowerShell steps and their Python fallbacks behave identically.

The Python fallback is always tested. The PowerShell scripts are tested too when a PowerShell
host that can run scripts is available (Windows PowerShell 5.1 or pwsh 7); otherwise those cases
are skipped with the reason.
"""

from __future__ import annotations

import functools
import os
import subprocess
from pathlib import Path

import pytest

from estate.paths import CODE_ROOT
from estate.shell import (
    ShellChoice,
    ShellUnavailableError,
    is_clixml_noise,
    powershell_command,
    python_command,
    resolve_shell,
)

IMPLEMENTATIONS = ["python", "powershell"]
SCV_NAME = "CBS-2026-001_SCV.csv"
PS_DIR = CODE_ROOT / "estate" / "powershell"


@functools.lru_cache(maxsize=1)
def _powershell_or_reason() -> ShellChoice | str:
    """Probe once per test session (starting PowerShell takes about a second)."""
    try:
        return resolve_shell("powershell")
    except ShellUnavailableError as exc:
        return str(exc)


def _powershell() -> ShellChoice:
    choice = _powershell_or_reason()
    if isinstance(choice, str):
        pytest.skip(f"PowerShell cannot run scripts here: {choice}")
    return choice


def run_step(implementation: str, script: str, module: str, params: dict[str, str]) -> subprocess.CompletedProcess[str]:
    if implementation == "powershell":
        command = powershell_command(_powershell().executable, PS_DIR / script, params)
    else:
        command = python_command(module, params)
    env = dict(os.environ, PYTHONPATH=str(CODE_ROOT), PYTHONIOENCODING="utf-8")
    return subprocess.run(command, cwd=str(CODE_ROOT), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, check=False)


def stderr_text(result: subprocess.CompletedProcess[str]) -> str:
    """stderr without Windows PowerShell progress records ("#< CLIXML ...")."""
    return "\n".join(line for line in result.stderr.splitlines() if not is_clixml_noise(line)).strip()


def publish(implementation: str, results: Path, outbound: Path) -> subprocess.CompletedProcess[str]:
    return run_step(
        implementation,
        "Publish-PaymentFile.ps1",
        "estate.steps.publish_payment_file",
        {"RunId": "RUN-0042", "CaseRef": "CBS-2026-001", "RunDate": "2026-10-05",
         "ResultsFile": str(results), "OutboundShare": str(outbound)},
    )


def stage(implementation: str, inbound: Path, processing: Path) -> subprocess.CompletedProcess[str]:
    return run_step(
        implementation,
        "Move-ScvFiles.ps1",
        "estate.steps.stage_files",
        {"RunId": "RUN-0042", "InboundShare": str(inbound), "ProcessingShare": str(processing), "FileName": SCV_NAME},
    )


def write_results(path: Path) -> Path:
    path.write_text(
        "depositor_id,compensation_gbp\nD0001,5000.00\nD0002,0.00\nD0003,120000.00\nD0004,33.34\n", encoding="utf-8"
    )
    return path


@pytest.mark.parametrize("implementation", IMPLEMENTATIONS)
def test_publish_fails_loudly_when_the_outbound_share_is_missing(implementation: str, tmp_path: Path) -> None:
    missing = tmp_path / "share" / "outbound-v2"
    result = publish(implementation, write_results(tmp_path / "payout_results.csv"), missing)
    assert result.returncode == 1
    assert stderr_text(result) == f"Outbound share not found: {missing}"
    assert result.stdout.strip() == ""


@pytest.mark.parametrize("implementation", IMPLEMENTATIONS)
def test_publish_writes_a_reconciled_payment_file(implementation: str, tmp_path: Path) -> None:
    outbound = tmp_path / "outbound"
    outbound.mkdir()
    result = publish(implementation, write_results(tmp_path / "payout_results.csv"), outbound)
    assert result.returncode == 0, result.stderr
    written = outbound / "PAY_CBS-2026-001_RUN-0042.csv"
    assert written.read_bytes() == (
        b"H,CBS-2026-001,RUN-0042,2026-10-05\nD,D0001,5000.00\nD,D0003,120000.00\nD,D0004,33.34\nT,3,125033.34\n"
    )
    assert not list(outbound.glob("*.partial")), "no partial files left behind"
    lines = result.stdout.splitlines()
    assert lines[0] == "Publishing PAY_CBS-2026-001_RUN-0042.csv: 3 payment records, total 125033.34"
    assert lines[1].startswith(f"Published PAY_CBS-2026-001_RUN-0042.csv to {outbound} (sha256 ")


@pytest.mark.parametrize("implementation", IMPLEMENTATIONS)
def test_stage_moves_the_scv_into_the_run_folder(implementation: str, tmp_path: Path) -> None:
    inbound, processing = tmp_path / "inbound", tmp_path / "processing"
    inbound.mkdir()
    processing.mkdir()
    (inbound / SCV_NAME).write_text("account_id\n", encoding="utf-8")
    result = stage(implementation, inbound, processing)
    assert result.returncode == 0, result.stderr
    assert (processing / "RUN-0042" / SCV_NAME).is_file()
    assert not (inbound / SCV_NAME).exists()
    assert result.stdout.strip() == f"Moved {SCV_NAME} to {processing / 'RUN-0042'}"


@pytest.mark.parametrize("implementation", IMPLEMENTATIONS)
def test_stage_reports_a_missing_scv_file(implementation: str, tmp_path: Path) -> None:
    inbound, processing = tmp_path / "inbound", tmp_path / "processing"
    inbound.mkdir()
    result = stage(implementation, inbound, processing)
    assert result.returncode == 1
    assert stderr_text(result) == f"SCV file not found: {inbound / SCV_NAME}"
