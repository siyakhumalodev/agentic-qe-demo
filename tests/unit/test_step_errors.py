"""A failed step is reported with a readable reason, even when Windows PowerShell adds progress noise.

Windows PowerShell 5.1 can write progress records ("#< CLIXML" + "<Objs ...>") to a redirected
stderr. The run's failure reason must still be the step's own message, e.g.
"Publish step failed (exit code 1): Outbound share not found: ...".
"""

from __future__ import annotations

from estate.coordinator import StepResult
from estate.shell import is_clixml_noise

PROGRESS_NOISE = (
    "#< CLIXML\n"
    '<Objs Version="1.1.0.1"><Obj S="progress" RefId="0"><TN RefId="0">'
    "<T>System.Management.Automation.PSCustomObject</T></TN></Obj></Objs>\n"
)
MESSAGE = "Outbound share not found: C:\\kit\\runtime\\share\\outbound-v2"


def test_first_error_line_skips_powershell_progress_records() -> None:
    result = StepResult("Publish-PaymentFile.ps1", 1, "", PROGRESS_NOISE + MESSAGE + "\n", 0.4)
    assert result.first_error_line == MESSAGE


def test_first_error_line_is_empty_when_stderr_is_only_noise() -> None:
    assert StepResult("Publish-PaymentFile.ps1", 1, "", PROGRESS_NOISE, 0.1).first_error_line == ""


def test_plain_error_output_is_unchanged() -> None:
    assert StepResult("publish_payment_file", 1, "", f"\n{MESSAGE}\n", 0.1).first_error_line == MESSAGE


def test_clixml_noise_detection() -> None:
    assert is_clixml_noise("#< CLIXML")
    assert is_clixml_noise('  <Objs Version="1.1.0.1">')
    assert not is_clixml_noise(MESSAGE)
    assert not is_clixml_noise("")
