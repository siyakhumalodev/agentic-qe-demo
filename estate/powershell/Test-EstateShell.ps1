<#
.SYNOPSIS
    Health probe: proves this PowerShell host can run the estate's scripts.

.DESCRIPTION
    Used by ESTATE_SHELL=auto. If execution policy, a blocked file or a restricted language mode
    (for example Constrained Language Mode enforced by device policy) stops this script, the
    estate falls back to the Python implementations of the two PowerShell steps. The probe uses
    the same .NET calls as the step scripts (UTF-8 output stream, file APIs), so "usable" here
    means the real steps will run too.
#>
[CmdletBinding()]
param()

$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$languageMode = [string]$ExecutionContext.SessionState.LanguageMode
if ($languageMode -ne 'FullLanguage') {
    Write-Output "PowerShell language mode is $languageMode; the estate steps need FullLanguage"
    exit 1
}

try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    $stdOut = New-Object System.IO.StreamWriter([Console]::OpenStandardOutput(), $utf8NoBom)
    $stdOut.AutoFlush = $true
    $null = [System.IO.File]::Exists($PSCommandPath)
    $stdOut.WriteLine('estate-shell-ok')
    exit 0
}
catch {
    Write-Output "PowerShell probe failed: $($_.Exception.Message)"
    exit 3
}
