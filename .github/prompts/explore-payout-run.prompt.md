---
agent: Cross-System Test Author
description: Demo 2 - explore the payout run in the browser, verify behind the UI and write a deterministic cross-system test.
---
Explore the "Start payout run" journey for case CBS-2026-001 in the portal at http://localhost:8085. Then verify what happened behind the UI using the estate tools: run status, VM lifecycle, files on the share, payout totals in the database and the payment file. Finally write a deterministic pytest in tests/e2e/test_payout_run_cross_system.py that checks all of this using tests/support/estate_probe.py, and run it.
