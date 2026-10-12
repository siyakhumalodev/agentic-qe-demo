"""Estate configuration, the simulated patch and the logical reset (all in a temporary estate root)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from estate.db import ControlStore
from estate.paths import EstateConfig, EstatePaths, estate_speed
from estate.runtime import ensure_runtime, logical_reset, set_patch_drift

PATCH_OVERRIDE = {
    "outbound_share": "runtime/share/outbound-v2",
    "_note": "Applied by server patch KB-DEMO-0042 (simulated)",
}


@pytest.fixture
def paths(tmp_path: Path) -> EstatePaths:
    estate_paths = EstatePaths.from_env(tmp_path)
    ensure_runtime(estate_paths)
    return estate_paths


def test_runtime_layout_is_created(paths: EstatePaths) -> None:
    for area in ("inbound", "processing", "outbound", "archive"):
        assert (paths.root / "runtime" / "share" / area).is_dir()
    assert paths.control_db.is_file() and paths.payout_db.is_file()
    assert (paths.root / "runtime" / "vms").is_dir()
    for component in ("portal", "coordinator", "steps", "etl"):
        assert paths.log_file(component).is_file()


def test_patch_drift_writes_the_documented_override(paths: EstatePaths) -> None:
    config = set_patch_drift(paths, True)
    assert json.loads(paths.override_file.read_text(encoding="utf-8")) == PATCH_OVERRIDE
    assert not paths.override_file.read_bytes().startswith(b"\xef\xbb\xbf"), "UTF-8 without BOM"
    assert config.patch_drift
    assert config.share_path("outbound") == (paths.root / "runtime" / "share" / "outbound-v2").resolve()
    assert not config.share_path("outbound").exists(), "the patched outbound share must not exist"

    config = set_patch_drift(paths, False)
    assert not paths.override_file.exists()
    assert not config.patch_drift
    assert config.share_path("outbound") == config.share_path("outbound", baseline=True)


def test_patch_drift_off_keeps_unrelated_override_keys(paths: EstatePaths) -> None:
    paths.override_file.write_text(json.dumps({"poll_interval_seconds": 1}), encoding="utf-8")
    set_patch_drift(paths, True)
    config = set_patch_drift(paths, False)
    assert config.override == {"poll_interval_seconds": 1}
    assert config.get("poll_interval_seconds") == 1


def test_effective_config_is_baseline_merged_with_override(paths: EstatePaths) -> None:
    paths.override_file.write_text(json.dumps({"step_delays_seconds": {"PUBLISHING": 9}}), encoding="utf-8")
    config = EstateConfig.load(paths)
    assert config.effective["step_delays_seconds"]["PUBLISHING"] == 9
    assert config.effective["step_delays_seconds"]["ARCHIVING"] == config.baseline["step_delays_seconds"]["ARCHIVING"]
    assert config.portal_port == 8085
    assert config.case_ref == "CBS-2026-001"


def test_logical_reset_clears_data_but_keeps_the_patch(paths: EstatePaths) -> None:
    store = ControlStore(paths.control_db)
    store.create_run("CBS-2026-001")
    share = paths.root / "runtime" / "share"
    (share / "archive" / "RUN-0001").mkdir(parents=True)
    (share / "archive" / "RUN-0001" / "CBS-2026-001_SCV.csv").write_text("x", encoding="utf-8")
    (share / "outbound" / "PAY_CBS-2026-001_RUN-0001.csv").write_text("x", encoding="utf-8")
    (share / "outbound-v2").mkdir()  # e.g. created by hand to "fix" the patch
    (paths.root / "runtime" / "vms" / "RUN-0001").mkdir()
    set_patch_drift(paths, True)

    summary = logical_reset(paths)

    assert summary.runs_removed == 1
    assert summary.files_removed == 2
    assert summary.vms_removed == 1
    assert summary.folders_removed == ["runtime/share/outbound-v2"]
    assert summary.patch_drift is True
    assert store.list_runs() == []
    assert not any((share / "outbound").iterdir())
    assert paths.control_db.is_file(), "databases are emptied, never deleted"
    assert EstateConfig.load(paths).patch_drift, "reset keeps the patch-drift state"


@pytest.mark.parametrize(("raw", "expected"), [("", 1.0), ("2", 2.0), ("0.5", 0.5), ("fast", 1.0), ("0", 0.1)])
def test_estate_speed_scales_delays(monkeypatch: pytest.MonkeyPatch, raw: str, expected: float) -> None:
    monkeypatch.setenv("ESTATE_SPEED", raw)
    assert estate_speed() == expected
