"""PROVISIONING_VM: create ``<vms-root>/<run-id>/`` from the VM template (two databases).

Usage: ``python -m estate.steps.provision_vm --run-id RUN-0001 --vms-root <dir> --template-dir <dir>``
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from estate.db import now_iso
from estate.steps.common import EXIT_INVALID_DATA, StepError, info, run_step


def provision(run_id: str, vms_root: Path, template_dir: Path) -> Path:
    """Create the VM folder with ``staging.db`` and ``work.db`` built from the template SQL."""
    manifest_file = template_dir / "vm.json"
    if not manifest_file.is_file():
        raise StepError(f"VM template not found: {manifest_file}")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    vm_dir = vms_root / run_id
    if vm_dir.exists():
        raise StepError(f"VM already exists: {vm_dir}", EXIT_INVALID_DATA)
    vm_dir.mkdir(parents=True)
    for database, schema_file in manifest["databases"].items():
        schema = (template_dir / schema_file).read_text(encoding="utf-8")
        conn = sqlite3.connect(str(vm_dir / database))
        try:
            conn.executescript(schema)
        finally:
            conn.close()
    vm_name = f"PAYOUT-VM-{run_id}"
    (vm_dir / "vm.json").write_text(
        json.dumps(
            {
                "vm_name": vm_name,
                "run_id": run_id,
                "template": manifest["template"],
                "databases": sorted(manifest["databases"]),
                "provisioned_at": now_iso(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    info(f"Provisioned {vm_name} from {manifest['template']} with {', '.join(sorted(manifest['databases']))}")
    return vm_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--vms-root", required=True, type=Path)
    parser.add_argument("--template-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    def body() -> None:
        provision(args.run_id, args.vms_root, args.template_dir)

    return run_step(body)


if __name__ == "__main__":
    sys.exit(main())
