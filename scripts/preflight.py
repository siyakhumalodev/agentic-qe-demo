"""Pre-flight check before a live session (run it with the estate already up).

    python scripts/preflight.py            checks + one headless payout run, verified behind the wall
    python scripts/preflight.py --no-run   checks only

Checks: estate running, coordinator alive, patch drift OFF, shell in use, .vscode/mcp.json,
Node.js/npx for the Playwright MCP server, git baseline tag - then starts one payout run through
the portal API and verifies it end to end with the same probe the cross-system test uses.
Exit code 0 = ready, 1 = something needs attention.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from estate.paths import EstateConfig, EstatePaths  # noqa: E402
from payout.config import DEPOSIT_LIMIT_GBP  # noqa: E402
from payout.money import format_gbp  # noqa: E402
from tests.support.estate_probe import (  # noqa: E402
    EstateProbe,
    Reconciliation,
    payout_summary,
    read_payment_file,
    start_payout_run,
    wait_for_terminal_run,
)


class Checklist:
    def __init__(self) -> None:
        self.failed = 0

    def check(self, ok: bool, label: str, fix: str = "") -> bool:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok or not fix else f"\n         -> {fix}"), flush=True)
        if not ok:
            self.failed += 1
        return ok

    def info(self, label: str) -> None:
        print(f"  [info] {label}", flush=True)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace", line_buffering=True)
    parser = argparse.ArgumentParser(description="Pre-flight check for the live demo.")
    parser.add_argument("--no-run", action="store_true", help="skip the headless payout run")
    args = parser.parse_args(argv)

    paths = EstatePaths.from_env()
    config = EstateConfig.load(paths)
    probe = EstateProbe(paths=paths)
    checks = Checklist()

    print("Environment")
    health = probe.health()
    portal = health["portal"]
    running = checks.check(portal["reachable"], f"estate running at {config.public_url}",
                           "start it in its own terminal: python -m estate up")
    if running:
        estate = portal["health"]
        checks.check(estate["coordinator"]["alive"], "coordinator polling", "restart: Ctrl+C, then python -m estate up")
        checks.info(f"estate shell: {estate['shell']}")
    checks.check(not config.patch_drift, "patch drift OFF", "python -m estate patch-drift off")
    checks.check(config.share_path("outbound").is_dir(), "outbound share exists", "python -m estate reset")

    mcp_json = REPO_ROOT / ".vscode" / "mcp.json"
    servers: dict[str, object] = {}
    if mcp_json.exists():
        try:
            servers = json.loads(mcp_json.read_text(encoding="utf-8-sig")).get("servers", {})
        except json.JSONDecodeError:
            servers = {}
    checks.check({"estate", "playwright"} <= set(servers), ".vscode/mcp.json has the estate and playwright servers",
                 "python scripts/setup.py")
    checks.check(bool(shutil.which("npx")), "npx available (Playwright MCP server)", "install Node.js 20+ LTS")
    tag = subprocess.run(["git", "tag", "--list", "demo-baseline"], cwd=REPO_ROOT, capture_output=True, text=True,
                         check=False).stdout.strip() if shutil.which("git") else ""
    checks.check(tag == "demo-baseline", "git tag demo-baseline present (for reset_demo.py)",
                 "git tag demo-baseline   (on a clean baseline)")

    if running and not args.no_run:
        print("\nHeadless payout run (portal API -> behind-the-wall checks)")
        run_id = start_payout_run(config.api_url)
        checks.info(f"started {run_id}; waiting for it to finish...")
        run = wait_for_terminal_run(probe, run_id)
        if checks.check(run["status"] == "COMPLETED", f"{run_id} COMPLETED in the control DB",
                        f"failure reason: {run['failure_reason']}"):
            events = [event["event"] for event in run["events"]]
            checks.check("VM_PROVISIONED" in events and "VM_DEPROVISIONED" in events and not run["vm"]["present"],
                         "VM provisioned, then deprovisioned")
            archived = {item["name"] for item in probe.list_share("archive")["files"]}
            checks.check(f"{run_id}/{config.scv_file_name}" in archived, "SCV file archived")
            payment = read_payment_file(probe, run_id)
            if checks.check(payment is not None, f"payment file published: {probe.payment_file_path(run_id).name}",
                            "see: python -m estate status, runtime/logs/steps.log"):
                assert payment is not None
                summary = payout_summary(probe, run_id)
                problems = Reconciliation(file=payment, db=summary).problems
                checks.check(not problems, f"file reconciles with the payout DB ({summary.payees} payees, "
                             f"{format_gbp(summary.total_compensation)})", "; ".join(problems))
                checks.check(payment.max_amount <= DEPOSIT_LIMIT_GBP,
                             f"no payment above the limit ({format_gbp(DEPOSIT_LIMIT_GBP)})")
        print("\n  Tip: run 'python -m estate reset' afterwards so the audience starts from a clean estate.")

    print(f"\n{'READY' if checks.failed == 0 else f'{checks.failed} check(s) need attention'}")
    return 0 if checks.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
