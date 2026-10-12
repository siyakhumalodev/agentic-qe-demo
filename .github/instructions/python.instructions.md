---
applyTo: "**/*.py"
description: Python conventions for the demo kit.
---

# Python conventions

- Python **3.11+** syntax; `from __future__ import annotations` at the top of modules (except
  `mcp_servers/estate/tools.py`, where FastMCP needs real annotations).
- **Type hints** on every function; **docstrings** on public modules, classes and functions (cite the
  rule ID, e.g. "R4", when implementing a business rule).
- **Money is `Decimal`** with 2 dp - never `float`. Use `payout.money` (`parse_gbp`, `format_gbp`,
  `to_money` rounds *down*, `to_pence`/`from_pence` for exact integer arithmetic).
- **Configuration** over literals: the limit is `payout.config.DEPOSIT_LIMIT_GBP`; estate settings come
  from `estate/config/estate.json` (+ runtime override).
- **`logging`**, not `print`, in library code (`logger = logging.getLogger(__name__)`). Command-line entry
  points may print user-facing messages.
- **`pathlib.Path`** for paths, `encoding="utf-8"` on every text read/write, no hard-coded separators.
- Fail loudly with clear messages; never swallow exceptions or ignore a subprocess exit code.
- Keep functions small and pure where possible; side effects at the edges (CLI, steps, portal).
- Format/lint style: PEP 8, line length 120.
