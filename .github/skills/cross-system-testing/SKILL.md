---
name: cross-system-testing
description: Pattern for testing journeys that cross UI, backend jobs, VMs, file shares, PowerShell steps and databases - drive the UI, then verify "behind the wall" with a read-only probe (estate MCP for agents, tests/support/estate_probe.py for pytest), with an assertion checklist and RCA evidence chain. Use when writing, reviewing or debugging end-to-end tests of the payout estate.
---

# Cross-system testing: look behind the wall

A UI that says "Completed" proves only that the UI says "Completed". Cross-system tests check the
**outcome** in every system the journey touches - using one read-only probe library shared by
agents (MCP) and tests (pytest), so both see the same truth.

## The estate (simulated, synthetic data)

```
Portal "Start payout run" -> control DB (QUEUED) -> coordinator (polls every 2 s)
  -> PROVISIONING_VM   runtime/vms/<run_id>/ from a template with staging.db + work.db
  -> STAGING_FILES     PowerShell Move-ScvFiles.ps1: inbound -> processing/<run_id>/
  -> LOADING_SCV       ETL: SCV -> VM staging.db
  -> CALCULATING       ETL: payout.rules -> work.db + runtime/db/payout.db
  -> PUBLISHING        PowerShell Publish-PaymentFile.ps1 -> outbound/PAY_CBS-2026-001_<run_id>.csv
  -> ARCHIVING         processing/<run_id>/ -> archive/<run_id>/
  -> DEPROVISIONING_VM VM folder removed
  -> COMPLETED | FAILED (reason)
```

Payment file: `H,<case>,<run_id>,<YYYY-MM-DD>` / `D,<depositor_id>,<amount>` (payees only) / `T,<count>,<total>`.

## Two doors to the same probe

| Who | How | API |
|---|---|---|
| Agents | `estate` MCP server (read-only, audited) | `estate_health`, `get_run`, `list_runs`, `list_share`, `read_share_file`, `query_db`, `tail_log`, `get_effective_config` |
| Tests | `tests/support/estate_probe.py` over `estate/probe.py` | `EstateProbe().get_run(...)`, `.list_share(...)`, `.payment_file_path(...)`, `wait_for_terminal_run`, `read_payment_file`, `payout_summary`, `Reconciliation`, `start_payout_run` |

Useful SQL (control DB): `SELECT step, exit_code, stderr_tail FROM run_steps WHERE run_id = 'RUN-0001' ORDER BY id`.
Payout DB: `SELECT COUNT(*), SUM(compensation_pence) FROM payout_results WHERE run_id = 'RUN-0001' AND compensation_pence > 0`.

## Assertion checklist for a payout run

1. UI reaches a final status; for the happy path, **Completed**.
2. Control DB status is **COMPLETED** (message includes the failure reason otherwise).
3. VM lifecycle: `VM_PROVISIONED` before `VM_DEPROVISIONED`; the VM folder is gone.
4. The SCV file is archived under `archive/<run_id>/`.
5. The payment file exists in the **effective** outbound share (`probe.payment_file_path(run_id)`) - failure
   message contains "Payment file not published".
6. Trailer count = number of `D` lines = payees in the payout DB.
7. Trailer total = sum of `D` lines = `SUM(compensation_pence)` in the payout DB = total shown in the UI.
8. No payment above `payout.config.DEPOSIT_LIMIT_GBP`.

## Determinism rules

- Poll with timeouts (`wait_for_terminal_run`, Playwright `expect(..., timeout=...)`); never `sleep`.
- Derive everything (run ID, totals, limit) from the UI, the probe or `payout.config`; hard-code nothing.
- Change the estate only through its public UI/API; observe it only through the probe.
- One run per test; never depend on another test's run.
- The estate must be running: `python -m estate up` (tests fail fast with that message otherwise).
- Negative paths: `start_payout_run(deliver_scv=False)` simulates a missing SCV delivery.

## RCA evidence chain (when a cross-system test fails)

Go from symptom to first cause, one layer at a time, citing the tool and value each time:
UI -> control DB (status, step exit codes) -> file shares -> step logs -> coordinator log ->
effective configuration -> code. Classify each cause separately: **test**, **product** or
**environment** defect. A green UI with a missing file is the signature of a *silent failure*.

## Anti-patterns

- Asserting only on the screen (false green). - Fixed sleeps. - Reading files by absolute path
  instead of the configured share. - Writing to the estate's databases from a test. - Sharing state between tests.
