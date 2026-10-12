"""Guardrails of the read-only ``estate`` MCP server and the shared probe library.

Runs against a temporary estate root, so it never touches the real runtime folder.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from estate.db import ControlStore, PayoutStore
from estate.paths import EstatePaths
from estate.probe import LIMITS, EstateProbe, GuardrailViolation, ProbeError, validate_select_sql
from estate.runtime import ensure_runtime
from mcp_servers.estate import tools
from payout.rules import calculate_compensation
from payout.scv import read_scv

SEED = Path(__file__).resolve().parents[2] / "estate" / "data" / "CBS-2026-001_SCV.csv"
EXPECTED_TOOLS = {
    "estate_health", "get_run", "list_runs", "list_share", "read_share_file", "query_db", "tail_log",
    "get_effective_config",
}


@pytest.fixture
def estate_root(tmp_path: Path) -> Iterator[Path]:
    paths = EstatePaths.from_env(tmp_path)
    ensure_runtime(paths)
    run_id = ControlStore(paths.control_db).create_run("CBS-2026-001")
    PayoutStore(paths.payout_db).replace_results(run_id, "CBS-2026-001", calculate_compensation(read_scv(SEED)))
    outbound = tmp_path / "runtime" / "share" / "outbound"
    (outbound / "PAY_CBS-2026-001_RUN-0001.csv").write_text(
        "H,CBS-2026-001,RUN-0001,2026-10-05\n" + "".join(f"D,D{i:04d},1.00\n" for i in range(1, 11)) + "T,10,10.00\n",
        encoding="utf-8",
    )
    paths.log_file("steps").write_text("".join(f"line {i}\n" for i in range(1, 1001)), encoding="utf-8")
    tools.configure(tmp_path)
    yield tmp_path
    tools.configure(None)


def audit_entries(root: Path) -> list[dict[str, object]]:
    path = root / "runtime" / "logs" / "mcp-audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_exactly_the_documented_read_only_tools_are_exposed() -> None:
    assert {function.__name__ for function in tools.TOOLS} == EXPECTED_TOOLS


@pytest.mark.parametrize(
    "name",
    [
        "../../db/control.db",
        "..\\..\\db\\payout.db",
        "RUN-0001/../../../db/control.db",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "c:/Windows/win.ini",
        "",
    ],
)
def test_path_traversal_and_absolute_paths_are_blocked(estate_root: Path, name: str) -> None:
    with pytest.raises(GuardrailViolation):
        tools.read_share_file("outbound", name)


def test_symlink_escape_is_blocked(estate_root: Path) -> None:
    link = estate_root / "runtime" / "share" / "outbound" / "escape.csv"
    try:
        os.symlink(estate_root / "runtime" / "db" / "control.db", link)
    except (OSError, NotImplementedError):
        pytest.skip("Symbolic links are not available for this user/OS")
    with pytest.raises(GuardrailViolation, match="escapes"):
        tools.read_share_file("outbound", "escape.csv")


@pytest.mark.parametrize(
    ("call", "arguments"),
    [
        (tools.list_share, {"area": "db"}),
        (tools.read_share_file, {"area": "../runtime", "name": "x"}),
        (tools.tail_log, {"component": "../../etc/passwd"}),
        (tools.query_db, {"database": "main", "sql": "SELECT 1"}),
    ],
    ids=["share-area", "share-area-traversal", "log-component", "database"],
)
def test_only_allow_listed_roots_are_reachable(estate_root: Path, call, arguments) -> None:  # noqa: ANN001
    with pytest.raises(GuardrailViolation):
        call(**arguments)


def test_a_share_configured_outside_the_runtime_folder_is_refused(estate_root: Path) -> None:
    override = estate_root / "runtime" / "config" / "estate.override.json"
    override.write_text(json.dumps({"outbound_share": "../outside"}), encoding="utf-8")
    with pytest.raises(GuardrailViolation, match="outside the estate runtime"):
        tools.list_share("outbound")


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM runs",
        "UPDATE runs SET status = 'COMPLETED'",
        "INSERT INTO runs (case_ref, status, requested_at) VALUES ('X', 'QUEUED', 'now')",
        "DROP TABLE runs",
        "CREATE TABLE notes (x)",
        "ALTER TABLE runs ADD COLUMN x",
        "PRAGMA writable_schema = 1",
        "ATTACH DATABASE 'other.db' AS other",
        "VACUUM",
        "WITH doomed AS (SELECT run_id FROM runs) DELETE FROM runs",
        "REPLACE INTO runs (run_id) VALUES ('RUN-9999')",
    ],
)
def test_only_select_queries_are_allowed(estate_root: Path, sql: str) -> None:
    with pytest.raises(GuardrailViolation):
        tools.query_db("control", sql)
    assert tools.query_db("control", "SELECT COUNT(*) FROM runs")["rows"] == [[1]], "nothing was changed"


@pytest.mark.parametrize(
    "sql",
    ["SELECT 1; DELETE FROM runs", "SELECT 1; SELECT 2", "SELECT 1;;SELECT 2", "SELECT 1; -- x\nDROP TABLE runs"],
)
def test_multiple_statements_are_rejected(estate_root: Path, sql: str) -> None:
    with pytest.raises(GuardrailViolation, match="Only one SQL statement"):
        tools.query_db("control", sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1;",
        "SELECT ';' AS semicolon",
        "select run_id from runs -- trailing; comment",
        "SELECT replace('a;b', ';', ',') AS cleaned",
        "WITH r AS (SELECT run_id, status FROM runs) SELECT * FROM r",
        'SELECT "status" FROM runs WHERE run_id = \'RUN-0001\'',
        "SELECT name FROM sqlite_master WHERE type = 'table'",
    ],
)
def test_legitimate_read_queries_are_allowed(estate_root: Path, sql: str) -> None:
    result = tools.query_db("control", sql)
    assert result["row_count"] >= 1


def test_the_connection_is_read_only_even_if_validation_is_bypassed(estate_root: Path) -> None:
    probe = EstateProbe(estate_root)
    with probe._readonly(probe.paths.control_db) as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM runs")  # denied by the authorizer
        conn.set_authorizer(None)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM runs")  # still refused: the database is opened read-only
    assert probe.query_db("control", "SELECT COUNT(*) FROM runs")["rows"] == [[1]]


def test_queries_have_a_time_limit(estate_root: Path) -> None:
    endless = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT COUNT(*) FROM n"
    with pytest.raises(ProbeError, match="time limit"):
        tools.query_db("payout", endless)


def test_rows_lines_and_listings_are_capped(estate_root: Path) -> None:
    capped = tools.query_db("payout", "SELECT depositor_id FROM payout_results", max_rows=1_000_000)
    assert capped["max_rows"] == LIMITS.max_rows

    small = tools.query_db("payout", "SELECT depositor_id FROM payout_results", max_rows=5)
    assert small["row_count"] == 5 and small["truncated"] is True

    log = tools.tail_log("steps", lines=1_000_000)
    assert len(log["lines"]) == LIMITS.max_lines
    assert log["lines"][-1] == "line 1000"

    head = tools.read_share_file("outbound", "PAY_CBS-2026-001_RUN-0001.csv", max_lines=3)
    assert head["lines"][0].startswith("H,CBS-2026-001") and len(head["lines"]) == 3
    assert head["truncated"] is True and head["total_lines"] == 12

    runs = tools.list_runs(limit=10_000)
    assert runs["limit"] == LIMITS.max_runs


def test_every_call_is_audited(estate_root: Path) -> None:
    before = len(audit_entries(estate_root))
    tools.list_share("outbound")
    with pytest.raises(GuardrailViolation):
        tools.query_db("control", "DELETE FROM runs")
    with pytest.raises(ProbeError):
        tools.get_run("RUN-9999")
    entries = audit_entries(estate_root)[before:]
    assert [(e["tool"], e["outcome"]) for e in entries] == [
        ("list_share", "ok"),
        ("query_db", "denied"),
        ("get_run", "error"),
    ]
    assert entries[1]["arguments"]["sql"] == "DELETE FROM runs"
    assert all(e["server"] == "estate" and e["ts"] for e in entries)


def test_select_validator_returns_the_single_statement() -> None:
    assert validate_select_sql("  SELECT 1 ;  ") == "SELECT 1"


def test_mcp_server_registers_the_tools() -> None:
    pytest.importorskip("mcp", reason="the MCP Python SDK is not installed")
    import asyncio

    from mcp_servers.estate import server

    listed = asyncio.run(server.mcp.list_tools())
    assert {tool.name for tool in listed} == EXPECTED_TOOLS
