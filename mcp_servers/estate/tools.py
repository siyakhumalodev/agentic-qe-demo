"""Tool functions of the read-only ``estate`` MCP server.

Each function is a thin, audited wrapper over ``estate.probe.EstateProbe`` - the same probe
library the deterministic tests use. Every call (allowed, denied or failed) is written to
``runtime/logs/mcp-audit.jsonl``. Guardrail violations are raised as errors, so the agent sees
why a request was refused.

Note: this module deliberately avoids ``from __future__ import annotations`` so that FastMCP
can read real type objects from the signatures.
"""

import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from estate.paths import EstatePaths
from estate.probe import EstateProbe, GuardrailViolation, ProbeError
from mcp_servers.estate.audit import AuditLog

_probe: Optional[EstateProbe] = None
_audit: Optional[AuditLog] = None


def configure(root: Optional[Path] = None) -> None:
    """Point the tools at an estate root (default: ``ESTATE_ROOT`` or the repository root)."""
    global _probe, _audit
    paths = EstatePaths.from_env(root)
    _probe = EstateProbe(paths=paths)
    _audit = AuditLog(paths.log_file("mcp-audit"))


def _get() -> "tuple[EstateProbe, AuditLog]":
    if _probe is None or _audit is None:
        configure()
    assert _probe is not None and _audit is not None
    return _probe, _audit


def _call(tool: str, arguments: Dict[str, Any], action: Callable[[EstateProbe], Dict[str, Any]]) -> Dict[str, Any]:
    probe, audit = _get()
    started = time.perf_counter()
    try:
        result = action(probe)
    except GuardrailViolation as exc:
        audit.record(tool, arguments, "denied", detail=str(exc), duration_ms=_elapsed(started))
        raise
    except ProbeError as exc:
        audit.record(tool, arguments, "error", detail=str(exc), duration_ms=_elapsed(started))
        raise
    except Exception as exc:
        audit.record(tool, arguments, "error", detail=f"{type(exc).__name__}: {exc}", duration_ms=_elapsed(started))
        raise
    audit.record(tool, arguments, "ok", detail=_summary(result), duration_ms=_elapsed(started))
    return result


def _elapsed(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _summary(result: Dict[str, Any]) -> str:
    for key in ("rows", "files", "lines", "runs", "events"):
        value = result.get(key)
        if isinstance(value, list):
            return f"{len(value)} {key}"
    return "ok"


def estate_health() -> Dict[str, Any]:
    """Overall health of the simulated estate: portal reachable, coordinator heartbeat, databases,
    the four share areas (effective paths and whether they exist), whether the simulated server
    patch (patch drift) is active, run counts by status and VMs currently provisioned."""
    return _call("estate_health", {}, lambda probe: probe.health())


def get_run(run_id: str) -> Dict[str, Any]:
    """Everything the control DB knows about one payout run: status, failure reason, payment file
    name, the status/event timeline, every step with its command and exit code (plus the tail of
    its stderr), and whether the run's VM folder still exists. run_id looks like RUN-0001."""
    return _call("get_run", {"run_id": run_id}, lambda probe: probe.get_run(run_id))


def list_runs(limit: int = 10) -> Dict[str, Any]:
    """The most recent payout runs (newest first) with status, failure reason and payment file.
    limit: 1-50 (default 10)."""
    return _call("list_runs", {"limit": limit}, lambda probe: probe.list_runs(limit))


def list_share(area: str) -> Dict[str, Any]:
    """List the files in one file-share area of the estate using the EFFECTIVE configuration
    (so a patched path shows up). area: one of inbound, processing, outbound, archive.
    Returns the configured path, whether the folder exists and each file's name, size and time."""
    return _call("list_share", {"area": area}, lambda probe: probe.list_share(area))


def read_share_file(area: str, name: str, max_lines: int = 200) -> Dict[str, Any]:
    """Read the first lines of a text file in a share area, e.g. a payment file
    (area='outbound', name='PAY_CBS-2026-001_RUN-0001.csv') or an archived SCV
    (area='archive', name='RUN-0001/CBS-2026-001_SCV.csv'). name is relative to the area;
    absolute paths and '..' are refused. max_lines: 1-500 (default 200)."""
    return _call(
        "read_share_file",
        {"area": area, "name": name, "max_lines": max_lines},
        lambda probe: probe.read_share_file(area, name, max_lines),
    )


def query_db(database: str, sql: str, max_rows: int = 100) -> Dict[str, Any]:
    """Run ONE read-only SQL query (SELECT or WITH only) against database 'control'
    (tables runs, run_events, run_steps) or 'payout' (tables payout_results, payout_runs; money as
    integer pence in *_pence columns). Connections are opened read-only; other statements are
    refused. Discover columns with: SELECT name, sql FROM sqlite_master. max_rows: 1-500."""
    return _call(
        "query_db",
        {"database": database, "sql": sql, "max_rows": max_rows},
        lambda probe: probe.query_db(database, sql, max_rows),
    )


def tail_log(component: str, lines: int = 50) -> Dict[str, Any]:
    """Last lines of a component log. component: one of portal, coordinator, steps (captured
    output and exit code of every step process, including the PowerShell steps), etl, mcp-audit.
    lines: 1-500 (default 50)."""
    return _call("tail_log", {"component": component, "lines": lines}, lambda probe: probe.tail_log(component, lines))


def get_effective_config() -> Dict[str, Any]:
    """The estate configuration: baseline (estate/config/estate.json), the runtime override file
    if present (for example one written by a server patch, with its _note), the merged effective
    values, the keys that differ from the baseline and where each share resolves."""
    return _call("get_effective_config", {}, lambda probe: probe.effective_config())


TOOLS = (
    estate_health,
    get_run,
    list_runs,
    list_share,
    read_share_file,
    query_db,
    tail_log,
    get_effective_config,
)
