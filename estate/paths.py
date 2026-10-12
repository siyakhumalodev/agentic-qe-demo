"""Locations and configuration of the simulated estate.

* Code-relative files (baseline config, VM template, PowerShell scripts, seed data) live next to
  this package.
* Runtime state lives under ``<root>/runtime`` (gitignored). ``root`` defaults to the repository
  root and can be overridden with the ``ESTATE_ROOT`` environment variable (used by tests).
* Effective configuration = baseline ``estate/config/estate.json`` merged with the optional
  override ``runtime/config/estate.override.json`` (written by ``python -m estate patch-drift on``).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

CODE_ROOT: Path = Path(__file__).resolve().parent.parent
PACKAGE_DIR: Path = Path(__file__).resolve().parent

SHARE_AREAS: tuple[str, ...] = ("inbound", "processing", "outbound", "archive")
LOG_COMPONENTS: tuple[str, ...] = ("portal", "coordinator", "steps", "etl", "mcp-audit")

PATCH_DRIFT_KEYS: dict[str, str] = {
    "outbound_share": "runtime/share/outbound-v2",
    "_note": "Applied by server patch KB-DEMO-0042 (simulated)",
}


class ConfigError(RuntimeError):
    """The estate configuration is missing or invalid."""


@dataclass(frozen=True)
class EstatePaths:
    """All file-system locations used by the estate for one runtime root."""

    root: Path
    code_root: Path = CODE_ROOT

    @classmethod
    def from_env(cls, root: Path | None = None) -> "EstatePaths":
        """Build paths from an explicit root, ``ESTATE_ROOT`` or the repository root."""
        if root is None:
            env_root = os.environ.get("ESTATE_ROOT", "").strip()
            root = Path(env_root) if env_root else CODE_ROOT
        return cls(root=root.resolve())

    @property
    def runtime(self) -> Path:
        return self.root / "runtime"

    @property
    def db_dir(self) -> Path:
        return self.runtime / "db"

    @property
    def control_db(self) -> Path:
        return self.db_dir / "control.db"

    @property
    def payout_db(self) -> Path:
        return self.db_dir / "payout.db"

    @property
    def logs_dir(self) -> Path:
        return self.runtime / "logs"

    @property
    def share_root(self) -> Path:
        return self.runtime / "share"

    @property
    def config_dir(self) -> Path:
        return self.runtime / "config"

    @property
    def override_file(self) -> Path:
        return self.config_dir / "estate.override.json"

    @property
    def pid_file(self) -> Path:
        return self.runtime / "estate.pid.json"

    @property
    def baseline_config_file(self) -> Path:
        return PACKAGE_DIR / "config" / "estate.json"

    @property
    def vm_template_dir(self) -> Path:
        return PACKAGE_DIR / "vm_template"

    @property
    def powershell_dir(self) -> Path:
        return PACKAGE_DIR / "powershell"

    def log_file(self, component: str) -> Path:
        """Return the log file for ``component`` (one of ``LOG_COMPONENTS``)."""
        if component not in LOG_COMPONENTS:
            raise ValueError(f"Unknown log component {component!r}; expected one of {', '.join(LOG_COMPONENTS)}")
        suffix = ".jsonl" if component == "mcp-audit" else ".log"
        return self.logs_dir / f"{component}{suffix}"

    def relative(self, path: Path) -> str:
        """Render ``path`` relative to the runtime root (POSIX separators) when possible."""
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path)


@dataclass(frozen=True)
class EstateConfig:
    """Effective configuration (baseline merged with the optional override)."""

    paths: EstatePaths
    baseline: Mapping[str, Any]
    override: Mapping[str, Any] | None
    effective: Mapping[str, Any]

    @classmethod
    def load(cls, paths: EstatePaths) -> "EstateConfig":
        """Load the baseline config and merge the override if present."""
        baseline = _read_json(paths.baseline_config_file, required=True)
        override = _read_json(paths.override_file, required=False)
        effective = merge_config(baseline, override or {})
        return cls(paths=paths, baseline=baseline, override=override, effective=effective)

    def get(self, key: str, default: Any = None) -> Any:
        return self.effective.get(key, default)

    @property
    def case_ref(self) -> str:
        return str(self.effective["case_ref"])

    @property
    def firm_name(self) -> str:
        return str(self.effective["firm_name"])

    @property
    def scv_file_name(self) -> str:
        return str(self.effective["scv_file_name"])

    @property
    def scv_seed_file(self) -> Path:
        return self.paths.code_root / str(self.effective["scv_seed_file"])

    @property
    def portal_host(self) -> str:
        return str(self.effective.get("portal_host", "127.0.0.1"))

    @property
    def portal_port(self) -> int:
        return int(self.effective.get("portal_port", 8085))

    @property
    def public_url(self) -> str:
        return str(self.effective.get("public_url", f"http://localhost:{self.portal_port}"))

    @property
    def api_url(self) -> str:
        """URL used by local tools and tests (IPv4 loopback avoids slow IPv6 fallbacks)."""
        return f"http://127.0.0.1:{self.portal_port}"

    @property
    def patch_drift(self) -> bool:
        return bool(self.override) and self.override.get("outbound_share") == PATCH_DRIFT_KEYS["outbound_share"]

    def share_path(self, area: str, *, baseline: bool = False) -> Path:
        """Absolute path of a share area from the effective (or baseline) configuration."""
        if area not in SHARE_AREAS:
            raise ValueError(f"Unknown share area {area!r}; expected one of {', '.join(SHARE_AREAS)}")
        source = self.baseline if baseline else self.effective
        return (self.paths.root / str(source[f"{area}_share"])).resolve()

    @property
    def vms_root(self) -> Path:
        return (self.paths.root / str(self.effective["vms_root"])).resolve()

    def vm_dir(self, run_id: str) -> Path:
        return self.vms_root / run_id

    def step_delay(self, status: str) -> float:
        """Simulated duration of a step in seconds, scaled by ``ESTATE_SPEED``."""
        delays = self.effective.get("step_delays_seconds", {}) or {}
        return float(delays.get(status, 0.0)) / estate_speed()


def merge_config(baseline: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``baseline`` (override wins)."""
    merged: dict[str, Any] = dict(baseline)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def estate_speed() -> float:
    """Speed multiplier from ``ESTATE_SPEED`` (2 = twice as fast, 0.5 = half speed)."""
    raw = os.environ.get("ESTATE_SPEED", "").strip()
    if not raw:
        return 1.0
    try:
        speed = float(raw)
    except ValueError:
        logger.warning("Ignoring invalid ESTATE_SPEED=%r (expected a number such as 2 or 0.5)", raw)
        return 1.0
    return min(max(speed, 0.1), 50.0)


def write_json_atomic(path: Path, data: Mapping[str, Any]) -> None:
    """Write JSON (UTF-8, no BOM) via a temporary file and an atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    for attempt in range(10):
        try:
            os.replace(temp, path)
            return
        except PermissionError:  # Windows: a reader may briefly hold the target open
            if attempt == 9:
                raise
            time.sleep(0.05 * (attempt + 1))


def _read_json(path: Path, *, required: bool) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            raise ConfigError(f"Configuration file not found: {path}")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Expected a JSON object in {path}")
    return data
