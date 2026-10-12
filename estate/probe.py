"""Read-only probe library: look "behind the wall" of the simulated estate.

Shared by the governed MCP server (``mcp_servers/estate``, used by agents) and the deterministic
tests (``tests/support/estate_probe.py``), so agents and CI observe the estate the same way.

Guardrails (enforced here, not by the caller):

* allow-listed roots only: the four share areas (which must sit under ``runtime/``), the two
  databases and the component logs - nothing else is reachable;
* path traversal blocked (absolute paths, ``..`` and symlink escapes are rejected);
* SQL: a single ``SELECT``/``WITH`` statement, validated, then run on a connection opened
  read-only (``mode=ro``), with ``PRAGMA query_only`` and an authorizer that denies writes;
* caps on rows, lines, listing size, file size and query time.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from estate.db import PayoutSummary
from estate.payment_file import payment_file_name
from estate.paths import LOG_COMPONENTS, SHARE_AREAS, EstateConfig, EstatePaths
from payout.money import from_pence


@dataclass(frozen=True)
class ProbeLimits:
    """Hard caps applied to every probe call."""

    max_rows: int = 500
    default_rows: int = 100
    max_lines: int = 500
    default_file_lines: int = 200
    default_log_lines: int = 50
    max_list_entries: int = 500
    max_runs: int = 50
    max_file_bytes: int = 2_000_000
    max_sql_chars: int = 5_000
    query_seconds: float = 2.0


LIMITS = ProbeLimits()
DATABASES: tuple[str, ...] = ("control", "payout")
RUN_ID_PATTERN = re.compile(r"^RUN-\d{4,}$")

FORBIDDEN_SQL_KEYWORDS = frozenset(
    {
        "INSERT", "UPDATE", "DELETE", "REPLACE", "UPSERT", "MERGE", "DROP", "ALTER", "CREATE", "ATTACH",
        "DETACH", "PRAGMA", "VACUUM", "REINDEX", "ANALYZE", "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT",
        "RELEASE", "TRUNCATE", "GRANT", "REVOKE", "LOAD_EXTENSION",
    }
)

_ALLOWED_SQL_ACTIONS = frozenset(
    {
        getattr(sqlite3, "SQLITE_READ", 20),
        getattr(sqlite3, "SQLITE_SELECT", 21),
        getattr(sqlite3, "SQLITE_FUNCTION", 31),
        getattr(sqlite3, "SQLITE_RECURSIVE", 33),
    }
)


class ProbeError(Exception):
    """A probe call could not be completed (bad input or missing data)."""


class GuardrailViolation(ProbeError):
    """A probe call was blocked by a guardrail."""


def validate_select_sql(sql: str) -> str:
    """Return the single read-only statement in ``sql`` or raise ``GuardrailViolation``.

    Comments, string literals and quoted identifiers are understood, so ``SELECT ';'`` is one
    statement and ``SELECT 1; DELETE FROM runs`` is two.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise GuardrailViolation("An SQL query is required")
    if len(sql) > LIMITS.max_sql_chars:
        raise GuardrailViolation(f"SQL is longer than {LIMITS.max_sql_chars} characters")

    statements: list[str] = []
    keywords_per_statement: list[list[tuple[str, str]]] = []
    current: list[str] = []
    keywords: list[tuple[str, str]] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end
            current.append(" ")
            continue
        if ch == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end == -1:
                raise GuardrailViolation("Unterminated /* comment */ in SQL")
            i = end + 2
            current.append(" ")
            continue
        if ch in ("'", '"', "`", "["):
            closing = "]" if ch == "[" else ch
            j = i + 1
            while True:
                j = sql.find(closing, j)
                if j == -1:
                    raise GuardrailViolation("Unterminated quoted string or identifier in SQL")
                if closing != "]" and sql.startswith(closing * 2, j):
                    j += 2  # escaped quote ('' or "")
                    continue
                break
            current.append(sql[i : j + 1])
            i = j + 1
            continue
        if ch == ";":
            statements.append("".join(current))
            keywords_per_statement.append(keywords)
            current, keywords = [], []
            i += 1
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            word = sql[i:j]
            following = sql[j:].lstrip()[:1]
            keywords.append((word.upper(), following))
            current.append(word)
            i = j
            continue
        current.append(ch)
        i += 1
    statements.append("".join(current))
    keywords_per_statement.append(keywords)

    non_empty = [(text.strip(), kws) for text, kws in zip(statements, keywords_per_statement) if text.strip()]
    if len(non_empty) != 1:
        raise GuardrailViolation("Only one SQL statement is allowed per call")
    statement, words = non_empty[0]
    if not words or words[0][0] not in ("SELECT", "WITH"):
        raise GuardrailViolation("Only read-only SELECT or WITH queries are allowed")
    for word, following in words:
        if word == "REPLACE" and following == "(":
            continue  # replace(...) is a string function, not REPLACE INTO
        if word in FORBIDDEN_SQL_KEYWORDS:
            raise GuardrailViolation(f"Keyword {word} is not allowed in a read-only query")
    return statement


def _read_only_authorizer(action: int, *_: Any) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED_SQL_ACTIONS else sqlite3.SQLITE_DENY


def _clamp(value: Any, default: int, maximum: int, what: str) -> int:
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ProbeError(f"{what} must be a whole number") from exc
    return max(1, min(number, maximum))


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Decimal):
        return str(value)
    return value


class EstateProbe:
    """Read-only, guarded view of one estate runtime."""

    def __init__(self, root: Path | None = None, *, paths: EstatePaths | None = None) -> None:
        self.paths = paths or EstatePaths.from_env(root)

    @property
    def config(self) -> EstateConfig:
        """Effective configuration, re-read on every call (reflects a simulated patch at once)."""
        return EstateConfig.load(self.paths)

    # -- MCP-facing operations ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Portal reachability, databases, shares, patch drift and run counts."""
        config = self.config
        portal: dict[str, Any] = {"url": config.public_url, "reachable": False}
        try:
            with urllib.request.urlopen(f"{config.api_url}/api/health", timeout=1.5) as response:
                portal["reachable"] = True
                portal["health"] = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            portal["error"] = f"{type(exc).__name__}: {exc}"
        databases = {name: self._db_path(name).is_file() for name in DATABASES}
        runs_by_status: dict[str, int] = {}
        if databases["control"]:
            result = self.query_db("control", "SELECT status, COUNT(*) FROM runs GROUP BY status")
            runs_by_status = {str(row[0]): int(row[1]) for row in result["rows"]}
        vms_root = config.vms_root
        active_vms = sorted(p.name for p in vms_root.iterdir() if p.is_dir()) if vms_root.is_dir() else []
        return {
            "portal": portal,
            "databases": databases,
            "shares": {area: self._share_status(config, area) for area in SHARE_AREAS},
            "patch_drift": config.patch_drift,
            "runs_by_status": runs_by_status,
            "active_vms": active_vms,
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Run row, status timeline, step exit codes and VM presence from the control DB."""
        run_id = self._check_run_id(run_id)
        with self._readonly(self._db_path("control")) as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise ProbeError(f"Run {run_id} not found in the control DB")
            run = {key: row[key] for key in row.keys() if key != "id"}
            run["deliver_scv"] = bool(run.get("deliver_scv", 1))
            run["events"] = [
                dict(item) for item in conn.execute(
                    "SELECT ts, event, status, message FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
                )
            ]
            run["steps"] = [
                dict(item) for item in conn.execute(
                    "SELECT step, command, started_at, finished_at, exit_code, stderr_tail FROM run_steps "
                    "WHERE run_id = ? ORDER BY id",
                    (run_id,),
                )
            ]
        vm_dir = self.config.vm_dir(run_id)
        run["vm"] = {"name": f"PAYOUT-VM-{run_id}", "path": self.paths.relative(vm_dir), "present": vm_dir.exists()}
        return run

    def list_runs(self, limit: int | None = 10) -> dict[str, Any]:
        """Most recent runs first."""
        count = _clamp(limit, 10, LIMITS.max_runs, "limit")
        with self._readonly(self._db_path("control")) as conn:
            rows = conn.execute(
                "SELECT run_id, case_ref, status, requested_at, finished_at, failure_reason, payment_file "
                "FROM runs ORDER BY id DESC LIMIT ?",
                (count,),
            ).fetchall()
        return {"runs": [dict(row) for row in rows], "limit": count}

    def list_share(self, area: str) -> dict[str, Any]:
        """Files in a share area (the *effective* path, so a patched outbound share shows up)."""
        root = self._share_root(area)
        files: list[dict[str, Any]] = []
        truncated = False
        if root.is_dir():
            for item in sorted(root.rglob("*")):
                if not item.is_file():
                    continue
                if len(files) >= LIMITS.max_list_entries:
                    truncated = True
                    break
                stat = item.stat()
                files.append(
                    {
                        "name": item.relative_to(root).as_posix(),
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
                    }
                )
        return {"area": area, "path": self.paths.relative(root), "exists": root.is_dir(), "files": files,
                "truncated": truncated}

    def read_share_file(self, area: str, name: str, max_lines: int | None = None) -> dict[str, Any]:
        """First ``max_lines`` lines of a text file inside a share area."""
        root = self._share_root(area)
        path = self._safe_child(root, name)
        if not path.is_file():
            raise ProbeError(f"File not found in the {area} share: {name}")
        size = path.stat().st_size
        if size > LIMITS.max_file_bytes:
            raise GuardrailViolation(f"File is larger than the {LIMITS.max_file_bytes} byte limit")
        count = _clamp(max_lines, LIMITS.default_file_lines, LIMITS.max_lines, "max_lines")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {
            "area": area,
            "name": path.relative_to(root.resolve()).as_posix(),
            "lines": lines[:count],
            "total_lines": len(lines),
            "truncated": len(lines) > count,
            "size": size,
        }

    def query_db(self, database: str, sql: str, max_rows: int | None = None) -> dict[str, Any]:
        """Run one read-only SELECT/WITH query against the control or payout DB."""
        statement = validate_select_sql(sql)
        count = _clamp(max_rows, LIMITS.default_rows, LIMITS.max_rows, "max_rows")
        with self._readonly(self._db_path(database)) as conn:
            deadline = time.monotonic() + LIMITS.query_seconds
            conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
            try:
                cursor = conn.execute(statement)
                rows = cursor.fetchmany(count + 1)
            except sqlite3.DatabaseError as exc:
                message = str(exc)
                if "interrupted" in message:
                    raise ProbeError(f"Query exceeded the {LIMITS.query_seconds:.0f}s time limit") from exc
                if "not authorized" in message or "readonly" in message:
                    raise GuardrailViolation(f"Blocked by the read-only connection: {message}") from exc
                raise ProbeError(f"SQL error: {message}") from exc
            columns = [column[0] for column in cursor.description or ()]
        return {
            "database": database,
            "columns": columns,
            "rows": [[_json_safe(value) for value in row] for row in rows[:count]],
            "row_count": min(len(rows), count),
            "truncated": len(rows) > count,
            "max_rows": count,
        }

    def tail_log(self, component: str, lines: int | None = None) -> dict[str, Any]:
        """Last ``lines`` lines of a component log."""
        if component not in LOG_COMPONENTS:
            raise GuardrailViolation(f"Unknown log component {component!r}; allowed: {', '.join(LOG_COMPONENTS)}")
        count = _clamp(lines, LIMITS.default_log_lines, LIMITS.max_lines, "lines")
        path = self.paths.log_file(component)
        if not path.is_file():
            return {"component": component, "exists": False, "lines": []}
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            tail = deque((line.rstrip("\n") for line in handle), maxlen=count)
        return {"component": component, "exists": True, "path": self.paths.relative(path), "lines": list(tail)}

    def effective_config(self) -> dict[str, Any]:
        """Baseline vs override vs effective configuration, plus where each share resolves."""
        config = self.config
        differences = [
            {"key": key, "baseline": config.baseline.get(key), "effective": value}
            for key, value in config.effective.items()
            if not key.startswith("_") and config.baseline.get(key) != value
        ]
        return {
            "baseline_file": "estate/config/estate.json",
            "override_file": self.paths.relative(self.paths.override_file),
            "override_present": config.override is not None,
            "override": config.override,
            "effective": dict(config.effective),
            "differences": differences,
            "patch_drift": config.patch_drift,
            "shares": {area: self._share_status(config, area) for area in SHARE_AREAS},
        }

    # -- helpers for deterministic tests --------------------------------------------------------

    def share_dir(self, area: str) -> Path:
        """Absolute, allow-listed path of a share area (effective configuration)."""
        return self._share_root(area)

    def payment_file_path(self, run_id: str) -> Path:
        """Where the payment file for ``run_id`` must be published (effective outbound share)."""
        run_id = self._check_run_id(run_id)
        return self._share_root("outbound") / payment_file_name(self.config.case_ref, run_id)

    def payout_summary(self, run_id: str) -> PayoutSummary | None:
        """Depositors, payees, total and largest payment for a run, straight from the payout DB."""
        run_id = self._check_run_id(run_id)
        with self._readonly(self._db_path("payout")) as conn:
            row = conn.execute(
                "SELECT COUNT(*), SUM(CASE WHEN compensation_pence > 0 THEN 1 ELSE 0 END), "
                "COALESCE(SUM(compensation_pence), 0), COALESCE(MAX(compensation_pence), 0) "
                "FROM payout_results WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None or int(row[0]) == 0:
            return None
        return PayoutSummary(run_id, int(row[0]), int(row[1] or 0), from_pence(int(row[2])), from_pence(int(row[3])))

    # -- internals ------------------------------------------------------------------------------

    def _check_run_id(self, run_id: str) -> str:
        if not isinstance(run_id, str) or not RUN_ID_PATTERN.match(run_id.strip()):
            raise ProbeError(f"Invalid run id {run_id!r}; run ids look like RUN-0001")
        return run_id.strip()

    def _db_path(self, database: str) -> Path:
        if database not in DATABASES:
            raise GuardrailViolation(f"Unknown database {database!r}; allowed: {', '.join(DATABASES)}")
        return self.paths.control_db if database == "control" else self.paths.payout_db

    def _share_root(self, area: str) -> Path:
        if area not in SHARE_AREAS:
            raise GuardrailViolation(f"Unknown share area {area!r}; allowed: {', '.join(SHARE_AREAS)}")
        root = self.config.share_path(area)
        if not root.is_relative_to(self.paths.runtime.resolve()):
            raise GuardrailViolation(f"The configured {area} share is outside the estate runtime folder")
        return root

    def _share_status(self, config: EstateConfig, area: str) -> dict[str, Any]:
        path = config.share_path(area)
        return {"path": self.paths.relative(path), "exists": path.is_dir()}

    @staticmethod
    def _safe_child(root: Path, name: str) -> Path:
        if not isinstance(name, str) or not name.strip() or "\x00" in name:
            raise GuardrailViolation("A file name relative to the share is required")
        normalized = name.strip().replace("\\", "/")
        if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
            raise GuardrailViolation("Absolute paths are not allowed; use a name relative to the share")
        parts = [part for part in normalized.split("/") if part not in ("", ".")]
        if any(part == ".." for part in parts):
            raise GuardrailViolation("Path traversal ('..') is not allowed")
        resolved_root = root.resolve()
        candidate = resolved_root.joinpath(*parts).resolve()
        if not candidate.is_relative_to(resolved_root):
            raise GuardrailViolation("The path escapes the allow-listed share")
        return candidate

    def _readonly(self, db_path: Path) -> "_ReadOnlyConnection":
        if not db_path.is_file():
            raise ProbeError(
                f"Database not found: {self.paths.relative(db_path)} (start the estate or run: python -m estate reset)"
            )
        return _ReadOnlyConnection(db_path)


class _ReadOnlyConnection:
    """Context manager for a read-only SQLite connection with an authorizer that denies writes."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.set_authorizer(_read_only_authorizer)
        self.conn = conn
        return conn

    def __exit__(self, *exc_info: object) -> None:
        if self.conn is not None:
            self.conn.close()
