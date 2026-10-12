"""Runtime initialisation, logical reset and the simulated server patch.

The reset is *logical*: it deletes rows and files but never deletes the SQLite database files
or open log files, so it is safe while the estate is running (including on Windows, where open
files cannot be deleted). When the estate is running, ``python -m estate reset`` asks it to do
the reset through its admin endpoint while it holds the coordinator's run lock.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from estate.db import ControlStore, PayoutStore, ensure_schema
from estate.logs import truncate_log
from estate.paths import LOG_COMPONENTS, PATCH_DRIFT_KEYS, SHARE_AREAS, EstateConfig, EstatePaths, write_json_atomic
from estate.steps.common import rmtree_robust

logger = logging.getLogger("estate.runtime")


@dataclass
class ResetSummary:
    """What a logical reset removed."""

    runs_removed: int = 0
    files_removed: int = 0
    vms_removed: int = 0
    folders_removed: list[str] = field(default_factory=list)
    logs_truncated: list[str] = field(default_factory=list)
    patch_drift: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def ensure_runtime(paths: EstatePaths) -> EstateConfig:
    """Create the runtime folders and databases if missing (idempotent). Returns the config."""
    config = EstateConfig.load(paths)
    for area in SHARE_AREAS:
        # Always create the *baseline* shares; a patched (overridden) path is deliberately not created.
        config.share_path(area, baseline=True).mkdir(parents=True, exist_ok=True)
    (paths.root / str(config.baseline["vms_root"])).mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    ensure_schema(paths.control_db, paths.payout_db)
    for component in LOG_COMPONENTS:
        paths.log_file(component).touch(exist_ok=True)
    return config


def logical_reset(paths: EstatePaths) -> ResetSummary:
    """Clear runs, payout results, shares, VMs and component logs. Keeps the patch-drift state."""
    config = ensure_runtime(paths)
    summary = ResetSummary(patch_drift=config.patch_drift)
    summary.runs_removed = ControlStore(paths.control_db).clear()
    PayoutStore(paths.payout_db).clear()

    baseline_shares = {config.share_path(area, baseline=True) for area in SHARE_AREAS}
    for share in sorted(baseline_shares):
        summary.files_removed += _empty_folder(share)
    # Remove extra folders under runtime/share (e.g. one created by hand to "fix" a patch).
    if paths.share_root.is_dir():
        for child in sorted(paths.share_root.iterdir()):
            if child.is_dir() and child.resolve() not in baseline_shares:
                rmtree_robust(child)
                summary.folders_removed.append(paths.relative(child))

    vms_root = paths.root / str(config.baseline["vms_root"])
    if vms_root.is_dir():
        for vm in sorted(vms_root.iterdir()):
            if vm.is_dir():
                rmtree_robust(vm)
                summary.vms_removed += 1
            else:
                _unlink_robust(vm)

    for component in LOG_COMPONENTS:
        if component == "mcp-audit":
            continue  # the MCP audit trail is append-only
        truncate_log(paths.log_file(component), "Log cleared by 'python -m estate reset'")
        summary.logs_truncated.append(component)
    logger.info("Estate reset: %s", summary.to_dict())
    return summary


def set_patch_drift(paths: EstatePaths, enabled: bool) -> EstateConfig:
    """Apply (``enabled``) or roll back the simulated server patch KB-DEMO-0042."""
    config = EstateConfig.load(paths)
    override = dict(config.override or {})
    if enabled:
        override.update(PATCH_DRIFT_KEYS)
    else:
        for key in PATCH_DRIFT_KEYS:
            override.pop(key, None)
    if override:
        write_json_atomic(paths.override_file, override)
    elif paths.override_file.exists():
        paths.override_file.unlink()
    return EstateConfig.load(paths)


def _empty_folder(folder: Path) -> int:
    """Delete everything inside ``folder`` (not the folder itself). Returns files removed."""
    removed = 0
    if not folder.is_dir():
        folder.mkdir(parents=True, exist_ok=True)
        return 0
    for child in folder.iterdir():
        if child.is_dir():
            removed += sum(1 for item in child.rglob("*") if item.is_file())
            rmtree_robust(child)
        else:
            _unlink_robust(child)
            removed += 1
    return removed


def _unlink_robust(path: Path, attempts: int = 10) -> None:
    """Delete a file, retrying briefly if another process (e.g. a reader) holds it on Windows."""
    for attempt in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.1 * (attempt + 1))
