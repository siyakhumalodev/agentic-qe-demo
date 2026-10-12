---
applyTo: "**/*.ps1"
description: Conventions for the estate's PowerShell steps (Windows PowerShell 5.1 and PowerShell 7+).
---

# PowerShell conventions

- Start every script with `[CmdletBinding()]`, a `param()` block with `[Parameter(Mandatory = $true)]`
  where required, then `Set-StrictMode -Version Latest` and **`$ErrorActionPreference = 'Stop'`**.
- **Explicit exit codes**: `exit 0` on success; `exit 1` missing share/file; `exit 2` invalid input;
  `exit 3` unexpected error (in a `catch`). The coordinator relies on them.
- Errors go to **stderr** as one clear line (`Outbound share not found: <path>`); progress to stdout.
  The scripts write UTF-8 (no BOM) through .NET stream writers so output is identical on every host.
- **Never use `-ErrorAction SilentlyContinue`** (or empty `catch {}`) on critical operations - a failure
  that is swallowed becomes a "green" run with missing output.
- Compatible with **Windows PowerShell 5.1 and pwsh 7**: no ternary `? :`, no `??`, no `-Parallel`;
  `Join-Path` with two arguments only; `-LiteralPath` for paths from parameters.
- Write files as **UTF-8 without BOM**: `[System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))`.
- Publish atomically: write `<name>.partial`, then rename.
- Parse and format numbers with `[System.Globalization.CultureInfo]::InvariantCulture`; money as `[decimal]`.
- Keep the Python fallback (`estate/steps/*.py`) behaviourally identical: same parameters (kebab-case),
  same messages, same exit codes. `tests/unit/test_step_parity.py` checks both.
- Scripts are invoked by the estate as `-NoProfile -NonInteractive [-ExecutionPolicy Bypass] -File <script> -Name value`.
- ASCII only in `.ps1` files (Windows PowerShell 5.1 reads BOM-less files as ANSI).
