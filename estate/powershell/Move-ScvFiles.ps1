<#
.SYNOPSIS
    STAGING_FILES step: moves the SCV file from the inbound share to the run's processing folder.

.DESCRIPTION
    Part of the simulated payout estate (fictional data only). Started by the coordinator as a
    separate process. Python fallback with identical behaviour: estate/steps/stage_files.py

    Exit codes: 0 success; 1 missing share or file; 2 invalid input; 3 unexpected error.
    Works with Windows PowerShell 5.1 and PowerShell 7+.

.EXAMPLE
    pwsh -NoProfile -File Move-ScvFiles.ps1 -RunId RUN-0001 -InboundShare C:\kit\runtime\share\inbound `
        -ProcessingShare C:\kit\runtime\share\processing -FileName CBS-2026-001_SCV.csv
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [Parameter(Mandatory = $true)][string]$InboundShare,
    [Parameter(Mandatory = $true)][string]$ProcessingShare,
    [Parameter(Mandatory = $true)][string]$FileName
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
    if (-not (Test-Path -LiteralPath $InboundShare -PathType Container)) {
        Write-StepError "Inbound share not found: $InboundShare"
        exit 1
    }

    $source = Join-Path $InboundShare $FileName
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        Write-StepError "SCV file not found: $source"
        exit 1
    }

    # .NET calls take literal paths (no wildcard expansion of characters such as [ or ]).
    $target = Join-Path $ProcessingShare $RunId
    [System.IO.Directory]::CreateDirectory($target) | Out-Null
    $destination = Join-Path $target $FileName
    if ([System.IO.File]::Exists($destination)) {
        [System.IO.File]::Delete($destination)
    }
    [System.IO.File]::Move($source, $destination)
    Write-StepInfo "Moved $FileName to $target"
    exit 0
}
catch {
    Write-StepError "Unexpected error: $($_.Exception.Message)"
    exit 3
}
