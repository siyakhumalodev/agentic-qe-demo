"""Append-only audit trail for every MCP tool call (``runtime/logs/mcp-audit.jsonl``)."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

_MAX_ARGUMENT_CHARS = 500


class AuditLog:
    """Writes one JSON object per line; safe to call from several threads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def record(
        self,
        tool: str,
        arguments: Mapping[str, Any],
        outcome: str,
        *,
        detail: str = "",
        duration_ms: float = 0.0,
    ) -> None:
        """Append one audit entry. ``outcome`` is ``ok``, ``denied`` (guardrail) or ``error``."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "server": "estate",
            "tool": tool,
            "arguments": {key: _truncate(value) for key, value in arguments.items()},
            "outcome": outcome,
            "detail": detail[:_MAX_ARGUMENT_CHARS],
            "duration_ms": round(duration_ms, 1),
            "pid": os.getpid(),
        }
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_ARGUMENT_CHARS:
        return value[:_MAX_ARGUMENT_CHARS] + "...(truncated)"
    return value
