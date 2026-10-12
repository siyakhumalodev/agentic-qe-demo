# Copilot instructions - agentic QE demo kit

This repository is a **self-contained demo** of agentic quality engineering: a simulated legacy
payout estate for a fictional failed deposit-taker ("Contoso Building Society", case
`CBS-2026-001`), a compensation rules engine, deterministic tests, a read-only MCP server and a team
of custom agents. All data is synthetic. Simplified rules for demonstration only — not FSCS policy.

## Layout

| Path | What |
|---|---|
| `payout/` | Compensation rules engine (`rules.py`, `config.py` with `DEPOSIT_LIMIT_GBP`, `money.py`, `scv.py`) |
| `estate/` | Simulated estate: portal (http://localhost:8085), coordinator, step processes, PowerShell scripts, read-only probe (`probe.py`) |
| `mcp_servers/estate/` | Read-only, audited MCP server over `estate/probe.py` |
| `tests/unit`, `tests/bdd` | Deterministic tests (pytest, pytest-bdd) - run in CI |
| `tests/e2e` | Browser + behind-the-UI tests (Playwright) - need the estate running |
| `tests/support/` | Shared helpers (`estate_probe.py`, `scv_builder.py`) |
| `reports/` | Agent outputs (analysis, traceability, RCA, migration notes) |
| `legacy/specflow-selenium/` | Legacy C# sample used for migration (not built or run) |
| `.github/agents`, `.github/skills`, `.github/instructions`, `.github/prompts` | The agent team and its rulebook |

## Commands

| Purpose | Command |
|---|---|
| Start the estate (own terminal) | `python -m estate up` |
| Estate health | `python -m estate status` |
| Reset estate data | `python -m estate reset` |
| Simulated server patch on/off | `python -m estate patch-drift on` / `off` |
| Unit + BDD tests | `pytest tests/unit tests/bdd` |
| One story | `pytest tests/bdd -m story_123` |
| End-to-end (estate running) | `pytest tests/e2e -m e2e` |
| Coverage | `pytest tests/unit tests/bdd --cov=payout --cov-report=term-missing` |

## Conventions

- Python 3.11+, type hints, docstrings, `logging` (no `print` in library code), `pathlib`, no
  hard-coded path separators. Money is `Decimal` with 2 dp (`payout.money`).
- The deposit limit is configured once in `payout/config.py`; never hard-code it anywhere else.
- Business rules come from the `deposit-compensation-rules` skill. If it is silent, ask - do not invent.
- Tests are deterministic: no sleeps, poll with timeouts, no randomness, synthetic IDs (`D0001`, `RUN-0001`).
- Agents author and heal tests; CI runs plain pytest. No LLM in the CI critical path.

## Guardrails

- Synthetic data only. Never connect to real systems, real file shares or production databases.
- Observe the estate through the `estate` MCP tools or `estate/probe.py` (read-only). Change it only
  through its portal/API or the documented `python -m estate ...` commands, and only when asked.
- Azure DevOps: use ADO MCP tools only if they are available; otherwise use the azure devops cli.
  and write previews to `reports/`.
- Never weaken, skip or delete a test to make it pass; product fixes need explicit human approval.
