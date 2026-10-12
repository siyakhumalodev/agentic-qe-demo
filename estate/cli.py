"""Command line for the simulated estate.

    python -m estate up                     start the portal + coordinator (Ctrl+C to stop)
    python -m estate status [--wait 60]     health of the running estate
    python -m estate reset                  logical data reset (safe while running; keeps patch drift)
    python -m estate patch-drift on|off     simulate server patch KB-DEMO-0042 / roll it back
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from estate.coordinator import Coordinator, recover_interrupted_runs
from estate.logs import attach_console_handler, configure_component, safe_console_streams
from estate.paths import EstateConfig, EstatePaths, write_json_atomic
from estate.portal import EstateHTTPServer, EstateHTTPServerV6, PortalContext, make_handler
from estate.probe import EstateProbe
from estate.runtime import ensure_runtime, logical_reset, set_patch_drift
from estate.shell import ShellUnavailableError, resolve_shell

logger = logging.getLogger("estate.cli")


def main(argv: list[str] | None = None) -> int:
    safe_console_streams()
    parser = argparse.ArgumentParser(
        prog="python -m estate",
        description="Simulated payout estate for the Contoso Building Society demo (fictional data).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("up", help="start the portal and the coordinator (Ctrl+C to stop)")
    status = sub.add_parser("status", help="show estate health")
    status.add_argument("--json", action="store_true", help="print machine-readable JSON")
    status.add_argument("--wait", type=float, default=0.0, metavar="SECONDS",
                        help="wait up to SECONDS for the estate to become healthy")
    sub.add_parser("reset", help="clear runs, results, shares, VMs and logs (keeps patch drift)")
    drift = sub.add_parser("patch-drift", help="simulate server patch KB-DEMO-0042 (on) or roll it back (off)")
    drift.add_argument("state", choices=("on", "off"))
    args = parser.parse_args(argv)

    paths = EstatePaths.from_env()
    try:
        if args.command == "up":
            return cmd_up(paths)
        if args.command == "status":
            return cmd_status(paths, as_json=args.json, wait=args.wait)
        if args.command == "reset":
            return cmd_reset(paths)
        return cmd_patch_drift(paths, args.state == "on")
    except BrokenPipeError:
        # Output was piped to a command that stopped reading (e.g. `| head`); the work is already done.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0


# -- up ----------------------------------------------------------------------------------------


def cmd_up(paths: EstatePaths) -> int:
    config = ensure_runtime(paths)
    configure_component("portal", paths)
    configure_component("coordinator", paths)
    attach_console_handler("estate")

    running = _portal_health(config)
    if running is not None:
        print(f"The estate is already running at {config.public_url} (pid {running.get('pid')}). "
              "Use 'python -m estate status', or stop the other terminal first.", file=sys.stderr)
        return 1
    try:
        shell = resolve_shell()
    except ShellUnavailableError as exc:
        print(f"Cannot start: {exc}", file=sys.stderr)
        return 2

    for run_id in recover_interrupted_runs(paths):
        print(f"Recovered interrupted run {run_id} (marked FAILED).")

    coordinator = Coordinator(paths, shell)
    context = PortalContext(
        paths=paths,
        coordinator=coordinator,
        admin_token=secrets.token_urlsafe(24),
        started_at=time.time(),
        reset=lambda: logical_reset(paths),
    )
    handler = make_handler(context)
    servers: list[EstateHTTPServer] = []
    try:
        servers.append(EstateHTTPServer((config.portal_host, config.portal_port), handler))
    except OSError as exc:
        print(f"Cannot listen on {config.portal_host}:{config.portal_port} ({exc}). "
              f"Is another program using port {config.portal_port}?", file=sys.stderr)
        return 1
    if config.portal_host in ("127.0.0.1", "localhost"):
        try:  # 'localhost' may resolve to ::1 first (Windows, macOS); serve both loopbacks.
            servers.append(EstateHTTPServerV6(("::1", config.portal_port), handler))
        except OSError as exc:
            logger.debug("IPv6 loopback not available: %s", exc)

    write_json_atomic(paths.pid_file, {
        "pid": os.getpid(),
        "port": config.portal_port,
        "url": config.public_url,
        "admin_token": context.admin_token,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    threads = [threading.Thread(target=server.serve_forever, name=f"portal-{i}", daemon=True)
               for i, server in enumerate(servers)]
    for thread in threads:
        thread.start()
    coordinator.start()

    print("")
    print("Contoso payout estate (simulated - synthetic data only)")
    print(f"  Portal:       {config.public_url}")
    print(f"  Coordinator:  polling every {coordinator.poll_interval():.1f}s")
    print(f"  Shell:        {shell.label}")
    if not shell.is_powershell:
        print(f"                ({shell.reason})")
    print(f"  Patch drift:  {'ON (KB-DEMO-0042)' if config.patch_drift else 'OFF'}")
    print(f"  Logs:         {paths.relative(paths.logs_dir)}/")
    print("Press Ctrl+C to stop.")
    print("", flush=True)
    logger.info("Estate started")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping the estate...", flush=True)
    finally:
        coordinator.stop()
        for server in servers:
            server.shutdown()
            server.server_close()
        try:
            paths.pid_file.unlink(missing_ok=True)
        except OSError:
            pass
        logging.getLogger("estate.portal").info("Estate stopped")
    return 0


# -- status ------------------------------------------------------------------------------------


def cmd_status(paths: EstatePaths, *, as_json: bool, wait: float) -> int:
    config = EstateConfig.load(paths)
    deadline = time.monotonic() + max(wait, 0.0)
    health = _portal_health(config)
    while health is None and time.monotonic() < deadline:
        time.sleep(0.5)
        health = _portal_health(config)

    probe = EstateProbe(paths=paths)
    report: dict[str, Any] = {"running": health is not None, "portal": health}
    try:
        report["estate"] = probe.health()
    except Exception as exc:  # noqa: BLE001 - status must always print something useful
        report["estate_error"] = str(exc)
    if health is None:
        try:
            report["shell_if_started"] = resolve_shell().label
        except ShellUnavailableError as exc:
            report["shell_if_started"] = f"unavailable: {exc}"
    try:
        report["last_run"] = probe.list_runs(1)["runs"][:1]
    except Exception:  # noqa: BLE001 - no database yet
        report["last_run"] = []

    if as_json:
        print(json.dumps(report, indent=2, default=str))
        return 0 if health is not None else 1

    print("Contoso payout estate - status")
    if health is None:
        print(f"  Portal:        NOT running at {config.public_url} - start it with: python -m estate up")
        print(f"  Shell:         {report.get('shell_if_started')} (when started)")
    else:
        coord = health.get("coordinator", {})
        print(f"  Portal:        running at {config.public_url} (pid {health.get('pid')}, "
              f"up {_duration(float(health.get('uptime_seconds', 0)))})")
        print(f"  Coordinator:   {'alive' if coord.get('alive') else 'NOT alive'}, last poll "
              f"{coord.get('last_poll_seconds_ago')}s ago, current run: {coord.get('current_run') or 'none'}")
        print(f"  Shell:         {health.get('shell')}")
    outbound = config.share_path("outbound")
    print(f"  Patch drift:   {'ON (KB-DEMO-0042)' if config.patch_drift else 'OFF'} - outbound share "
          f"{paths.relative(outbound)} ({'exists' if outbound.is_dir() else 'MISSING'})")
    runs = report.get("estate", {}).get("runs_by_status", {})
    print(f"  Runs:          {', '.join(f'{k} {v}' for k, v in sorted(runs.items())) or 'none'}")
    for run in report["last_run"]:
        detail = run.get("payment_file") or run.get("failure_reason") or ""
        print(f"  Last run:      {run['run_id']} {run['status']} {detail}".rstrip())
    return 0 if health is not None else 1


# -- reset -------------------------------------------------------------------------------------


def cmd_reset(paths: EstatePaths) -> int:
    config = ensure_runtime(paths)
    health = _portal_health(config)
    if health is not None:
        token = _admin_token(paths)
        if not token:
            print("The estate is running but runtime/estate.pid.json is missing; restart 'python -m estate up' "
                  "and try again.", file=sys.stderr)
            return 1
        request = urllib.request.Request(
            f"{config.api_url}/api/admin/reset", data=b"{}", method="POST",
            headers={"Content-Type": "application/json", "X-Estate-Admin-Token": token},
        )
        try:
            with urllib.request.urlopen(request, timeout=150) as response:
                summary = json.loads(response.read().decode("utf-8"))["reset"]
        except urllib.error.HTTPError as exc:
            print(f"Reset refused by the running estate: {exc.read().decode('utf-8', 'replace')}", file=sys.stderr)
            return 1
        mode = "via the running estate (logical reset under the coordinator lock)"
    else:
        summary = logical_reset(paths).to_dict()
        mode = "directly (estate not running)"
    print(f"Estate data reset {mode}:")
    print(f"  runs removed: {summary['runs_removed']}, share files removed: {summary['files_removed']}, "
          f"VMs removed: {summary['vms_removed']}")
    if summary["folders_removed"]:
        print(f"  extra share folders removed: {', '.join(summary['folders_removed'])}")
    print(f"  logs cleared: {', '.join(summary['logs_truncated'])} (mcp-audit kept)")
    print(f"  patch drift: {'ON (kept)' if summary['patch_drift'] else 'OFF'}")
    return 0


# -- patch drift -------------------------------------------------------------------------------


def cmd_patch_drift(paths: EstatePaths, enabled: bool) -> int:
    ensure_runtime(paths)
    config = set_patch_drift(paths, enabled)
    outbound = config.share_path("outbound")
    if enabled:
        print("Simulated server patch KB-DEMO-0042 applied.")
        print(f"  {paths.relative(paths.override_file)} now sets outbound_share = {paths.relative(outbound)} "
              f"(folder {'exists' if outbound.is_dir() else 'does not exist'}).")
        print("  New payout runs pick this up automatically - no restart needed.")
    else:
        print("Simulated server patch KB-DEMO-0042 rolled back.")
        print(f"  outbound_share = {paths.relative(outbound)} ({'exists' if outbound.is_dir() else 'MISSING'}).")
    return 0


# -- helpers -----------------------------------------------------------------------------------


def _portal_health(config: EstateConfig) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{config.api_url}/api/health", timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return payload if payload.get("service") == "contoso-payout-estate" else None


def _admin_token(paths: EstatePaths) -> str | None:
    try:
        return str(json.loads(paths.pid_file.read_text(encoding="utf-8"))["admin_token"])
    except (OSError, ValueError, KeyError):
        return None


def _duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {secs}s" if hours else f"{minutes}m {secs}s"
