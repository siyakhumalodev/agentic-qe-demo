"""DEPROVISIONING_VM: remove ``<vms-root>/<run-id>/`` (the VM and its two databases).

Usage: ``python -m estate.steps.deprovision_vm --run-id RUN-0001 --vms-root <dir>``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from estate.steps.common import info, rmtree_robust, run_step


def deprovision(run_id: str, vms_root: Path) -> None:
    vm_dir = vms_root / run_id
    if not vm_dir.exists():
        info(f"VM PAYOUT-VM-{run_id} already absent")
        return
    rmtree_robust(vm_dir)
    info(f"Deprovisioned PAYOUT-VM-{run_id} ({vm_dir} removed)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--vms-root", required=True, type=Path)
    args = parser.parse_args(argv)
    return run_step(lambda: deprovision(args.run_id, args.vms_root))


if __name__ == "__main__":
    sys.exit(main())
