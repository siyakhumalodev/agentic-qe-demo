<#
.SYNOPSIS
    PUBLISHING step: builds the payment file for a payout run and writes it to the outbound share.

.DESCRIPTION
    Part of the simulated payout estate (fictional data only). Started by the coordinator as a
    separate process. Python fallback with identical behaviour: estate/steps/publish_payment_file.py

    Reads the results extract written by the ETL step (depositor_id,compensation_gbp), writes
        H,<case_ref>,<run_id>,<YYYY-MM-DD>
        D,<depositor_id>,<amount 2dp>     (one line per depositor with compensation > 0)
        T,<record_count>,<total 2dp>
    to a .partial file (UTF-8 without BOM, LF line endings) and renames it into place.

    Exit codes: 0 success; 1 missing share or file; 2 invalid input data; 3 unexpected error.
    Works with Windows PowerShell 5.1 and PowerShell 7+.

.EXAMPLE
    pwsh -NoProfile -File Publish-PaymentFile.ps1 -RunId RUN-0001 -CaseRef CBS-2026-001 -RunDate 2026-10-05 `
        -ResultsFile C:\kit\runtime\share\processing\RUN-0001\payout_results.csv `
        -OutboundShare C:\kit\runtime\share\outbound
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [Parameter(Mandatory = $true)][string]$CaseRef,
    [Parameter(Mandatory = $true)][string]$RunDate,
    [Parameter(Mandatory = $true)][string]$ResultsFile,
    [Parameter(Mandatory = $true)][string]$OutboundShare
)

# Keep stderr clean: Windows PowerShell 5.1 can write progress records ("#< CLIXML ...") to a
# redirected stream, for example "Preparing modules for first use".
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Write UTF-8 (no BOM) to stdout/stderr directly so that output is identical on every host.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$stdOut = New-Object System.IO.StreamWriter([Console]::OpenStandardOutput(), $utf8NoBom)
$stdOut.AutoFlush = $true
$stdErr = New-Object System.IO.StreamWriter([Console]::OpenStandardError(), $utf8NoBom)
$stdErr.AutoFlush = $true

function Write-StepInfo {
    param([Parameter(Mandatory = $true)][string]$Message)
    $stdOut.WriteLine($Message)
}

function Write-StepError {
    param([Parameter(Mandatory = $true)][string]$Message)
    $stdErr.WriteLine($Message)
}

try {
    # Never continue silently: a missing outbound share is a failure (exit 1).
    if (-not (Test-Path -LiteralPath $OutboundShare -PathType Container)) {
        Write-StepError "Outbound share not found: $OutboundShare"
        exit 1
    }
    if (-not (Test-Path -LiteralPath $ResultsFile -PathType Leaf)) {
        Write-StepError "Results file not found: $ResultsFile"
        exit 1
    }

    $culture = [System.Globalization.CultureInfo]::InvariantCulture
    $rows = @(Import-Csv -LiteralPath $ResultsFile -Encoding UTF8)

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("H,$CaseRef,$RunId,$RunDate")
    $count = 0
    $total = [decimal]0
    foreach ($row in $rows) {
        $text = [string]$row.compensation_gbp
        if ($text -notmatch '^\d+\.\d{2}$') {
            Write-StepError "Invalid amount '$text' for depositor $($row.depositor_id) in $ResultsFile"
            exit 2
        }
        $amount = [decimal]::Parse($text, $culture)
        if ($amount -gt 0) {
            $lines.Add("D,$($row.depositor_id),$($amount.ToString('F2', $culture))")
            $count++
            $total += $amount
        }
    }
    $totalText = $total.ToString('F2', $culture)
    $lines.Add("T,$count,$totalText")

    $name = "PAY_${CaseRef}_${RunId}.csv"
    Write-StepInfo "Publishing ${name}: $count payment records, total $totalText"

    # Write a .partial file first, then rename, so downstream readers never see a half-written file.
    $target = Join-Path $OutboundShare $name
    $partial = "$target.partial"
    [System.IO.File]::WriteAllText($partial, (($lines -join "`n") + "`n"), $utf8NoBom)
    if ([System.IO.File]::Exists($target)) {
        [System.IO.File]::Delete($target)
    }
    [System.IO.File]::Move($partial, $target)

    $hash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-StepInfo "Published $name to $OutboundShare (sha256 $hash)"
    exit 0
}
catch {
    Write-StepError "Unexpected error: $($_.Exception.Message)"
    exit 3
}
