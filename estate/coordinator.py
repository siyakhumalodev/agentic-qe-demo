"""Coordinator: picks up queued payout runs and executes their steps.

It stands in for an on-premises job coordinator:

* ``Coordinator`` - the timed poller started by ``python -m estate up``. Every
  ``poll_interval_seconds`` it claims the oldest QUEUED run and hands it to a *fresh* executor
  process, so code changes take effect on the next run without restarting the estate.
* ``RunExecutor`` - ``python -m estate.coordinator execute --run-id RUN-0001``. Runs the pipeline;
  every step is a separate process (Python, or PowerShell for the two file-handling steps).
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from estate.db import ControlStore, PayoutStore, RunStatus
from estate.logs import configure_component
from estate.paths import EstateConfig, EstatePaths, estate_speed
from estate.payment_file import payment_file_name
from estate.shell import (
    RESOLVED_ENV,
    ShellChoice,
    is_clixml_noise,
    powershell_command,
    python_command,
    resolve_shell,
)
from estate.steps.common import rmtree_robust
from payout.money import format_gbp

logger = logging.getLogger("estate.coordinator")
steps_logger = logging.getLogger("estate.steps")
console_logger = logging.getLogger("estate.console")


@dataclass(frozen=True)
class StepSpec:
    """One step of the payout pipeline."""

    status: RunStatus
    display_name: str
    python_module: str
    powershell_script: str | None = None
    module_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepResult:
    """Outcome of one step process."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float

    @property
    def first_error_line(self) -> str:
        """First meaningful stderr line (Windows PowerShell progress records are skipped)."""
        return next(
            (line.strip() for line in self.stderr.splitlines() if line.strip() and not is_clixml_noise(line)),
            "",
        )


class StepFailedError(RuntimeError):
    """A step did not complete successfully, so the run must fail."""

    def __init__(self, spec: StepSpec, result: StepResult) -> None:
        detail = result.first_error_line or "no error output"
        super().__init__(f"{spec.display_name} step failed (exit code {result.exit_code}): {detail}")
        self.spec = spec
        self.result = result


PIPELINE: tuple[StepSpec, ...] = (
    StepSpec(RunStatus.PROVISIONING_VM, "Provision VM", "estate.steps.provision_vm"),
    StepSpec(RunStatus.STAGING_FILES, "Stage files", "estate.steps.stage_files", "Move-ScvFiles.ps1"),
    StepSpec(RunStatus.LOADING_SCV, "Load SCV", "estate.steps.etl", module_args=("load",)),
    StepSpec(RunStatus.CALCULATING, "Calculate", "estate.steps.etl", module_args=("calculate",)),
    StepSpec(RunStatus.PUBLISHING, "Publish", "estate.steps.publish_payment_file", "Publish-PaymentFile.ps1"),
    StepSpec(RunStatus.ARCHIVING, "Archive", "estate.steps.archive"),
)
DEPROVISION = StepSpec(RunStatus.DEPROVISIONING_VM, "Deprovision VM", "estate.steps.deprovision_vm")


class RunExecutor:
    """Executes one payout run (in its own process)."""

    def __init__(self, run_id: str, paths: EstatePaths, shell: ShellChoice) -> None:
        self.run_id = run_id
        self.paths = paths
        self.shell = shell
        # Configuration is read once per run, so a simulated patch applies from the next run.
        self.config = EstateConfig.load(paths)
        self.control = ControlStore(paths.control_db)
        self.run_date = date.today().isoformat()
        self._current_status: RunStatus | None = None
        self._vm_provisioned = False

    @property
    def vm_name(self) -> str:
        return f"PAYOUT-VM-{self.run_id}"

    def execute(self) -> RunStatus:
        """Run the pipeline and record the outcome in the control DB."""
        run = self.control.get_run(self.run_id)
        if run is None:
            raise ValueError(f"Unknown run {self.run_id}")
        self._current_status = RunStatus(run["status"])
        logger.info(
            "Run %s started (shell: %s, outbound share: %s)",
            self.run_id,
            self.shell.label,
            self.paths.relative(self.config.share_path("outbound")),
        )
        failure_reason: str | None = None
        try:
            self._receive_scv(bool(run["deliver_scv"]))
            for spec in PIPELINE:
                result = self._run_step(spec)
                logger.info(
                    "Run %s step %s finished with exit code %d (%.1fs)",
                    self.run_id, spec.status.value, result.exit_code, result.duration_s,
                )
                self._after_step(spec, result)
        except StepFailedError as exc:
            failure_reason = str(exc)
        except Exception as exc:  # noqa: BLE001 - any coordinator error must fail the run, not hang it
            logger.exception("Run %s: unexpected coordinator error", self.run_id)
            failure_reason = f"Coordinator error: {exc}"
        finally:
            self._deprovision_vm()

        if failure_reason:
            self.control.fail_run(self.run_id, failure_reason)
            logger.error("Run %s FAILED: %s", self.run_id, failure_reason)
            return RunStatus.FAILED
        payment_file = payment_file_name(self.config.case_ref, self.run_id)
        self.control.complete_run(self.run_id, payment_file)
        logger.info("Run %s COMPLETED (payment file %s)", self.run_id, payment_file)
        return RunStatus.COMPLETED

    # -- pipeline helpers -------------------------------------------------------------------

    def _receive_scv(self, deliver: bool) -> None:
        """Simulate the upstream feed: the firm's SCV file lands in the inbound share."""
        inbound = self.config.share_path("inbound")
        target = inbound / self.config.scv_file_name
        if not deliver:
            self.control.add_event(self.run_id, "SCV_NOT_DELIVERED", "Upstream feed delivery skipped (deliver_scv=false)")
            return
        if not target.exists():
            inbound.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".incoming")
            shutil.copyfile(self.config.scv_seed_file, temp)
            os.replace(temp, target)
        self.control.add_event(
            self.run_id,
            "SCV_RECEIVED",
            f"SCV file {target.name} received from {self.config.firm_name} in the inbound share",
        )

    def _run_step(self, spec: StepSpec) -> StepResult:
        if self._current_status is not spec.status:
            self.control.set_status(self.run_id, spec.status)
            self._current_status = spec.status
        time.sleep(self.config.step_delay(spec.status.value))  # simulated work, scaled by ESTATE_SPEED

        command, display = self._command(spec)
        step_row = self.control.start_step(self.run_id, spec.status, display)
        timeout = float(self.config.get("step_timeout_seconds", 120))
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.paths.code_root),
                env=self._child_env(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            result = StepResult(display, 127, "", f"Could not start the step: {exc}", time.monotonic() - started)
            self._record(spec, step_row, result)
            raise StepFailedError(spec, result) from exc
        except subprocess.TimeoutExpired as exc:
            result = StepResult(display, 124, "", f"Step timed out after {timeout:.0f}s", time.monotonic() - started)
            self._record(spec, step_row, result)
            raise StepFailedError(spec, result) from exc
        result = StepResult(display, completed.returncode, completed.stdout, completed.stderr,
                            time.monotonic() - started)
        self._record(spec, step_row, result)
        if result.exit_code != 0:
            raise StepFailedError(spec, result)
        return result

    def _after_step(self, spec: StepSpec, result: StepResult) -> None:
        if spec.status is RunStatus.PROVISIONING_VM and self.config.vm_dir(self.run_id).is_dir():
            self._vm_provisioned = True
            self.control.add_event(
                self.run_id, "VM_PROVISIONED",
                f"VM {self.vm_name} provisioned from template PAYOUT-VM-TEMPLATE (staging.db, work.db)",
            )
        elif spec.status is RunStatus.CALCULATING and result.exit_code == 0:
            summary = PayoutStore(self.paths.payout_db).summary(self.run_id)
            if summary is not None:
                self.control.add_event(
                    self.run_id, "CALCULATED",
                    f"{summary.depositors} depositors, {summary.payees} payees, "
                    f"total {format_gbp(summary.total_compensation)}",
                )

    def _deprovision_vm(self) -> None:
        """Always tear the VM down, whatever happened to the run."""
        try:
            result = self._run_step(DEPROVISION)
            logger.info(
                "Run %s step %s finished with exit code %d (%.1fs)",
                self.run_id, DEPROVISION.status.value, result.exit_code, result.duration_s,
            )
        except StepFailedError as exc:
            logger.error("Run %s: %s", self.run_id, exc)
        except Exception:  # noqa: BLE001 - never let clean-up mask the run outcome
            logger.exception("Run %s: VM clean-up failed", self.run_id)
        if self._vm_provisioned and not self.config.vm_dir(self.run_id).exists():
            self.control.add_event(self.run_id, "VM_DEPROVISIONED", f"VM {self.vm_name} deprovisioned")

    def _command(self, spec: StepSpec) -> tuple[list[str], str]:
        params = self._params(spec)
        if spec.powershell_script and self.shell.is_powershell:
            script = self.paths.powershell_dir / spec.powershell_script
            return powershell_command(self.shell.executable, script, params), f"{self.shell.kind} {spec.powershell_script}"
        display = " ".join(["python -m", spec.python_module, *spec.module_args])
        return python_command(spec.python_module, params, spec.module_args), display

    def _params(self, spec: StepSpec) -> dict[str, str]:
        config = self.config
        processing_dir = config.share_path("processing") / self.run_id
        vm_dir = config.vm_dir(self.run_id)
        by_status: dict[RunStatus, dict[str, str]] = {
            RunStatus.PROVISIONING_VM: {
                "VmsRoot": str(config.vms_root),
                "TemplateDir": str(self.paths.vm_template_dir),
            },
            RunStatus.STAGING_FILES: {
                "InboundShare": str(config.share_path("inbound")),
                "ProcessingShare": str(config.share_path("processing")),
                "FileName": config.scv_file_name,
            },
            RunStatus.LOADING_SCV: {
                "VmDir": str(vm_dir),
                "ScvFile": str(processing_dir / config.scv_file_name),
            },
            RunStatus.CALCULATING: {
                "VmDir": str(vm_dir),
                "CaseRef": config.case_ref,
                "PayoutDb": str(self.paths.payout_db),
                "ExtractFile": str(processing_dir / "payout_results.csv"),
            },
            RunStatus.PUBLISHING: {
                "CaseRef": config.case_ref,
                "RunDate": self.run_date,
                "ResultsFile": str(processing_dir / "payout_results.csv"),
                "OutboundShare": str(config.share_path("outbound")),
            },
            RunStatus.ARCHIVING: {
                "ProcessingShare": str(config.share_path("processing")),
                "ArchiveShare": str(config.share_path("archive")),
            },
            RunStatus.DEPROVISIONING_VM: {"VmsRoot": str(config.vms_root)},
        }
        return {"RunId": self.run_id, **by_status[spec.status]}

    def _child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        code_root = str(self.paths.code_root)
        env["PYTHONPATH"] = os.pathsep.join(p for p in (code_root, env.get("PYTHONPATH", "")) if p)
        env["PYTHONIOENCODING"] = "utf-8"
        env["ESTATE_ROOT"] = str(self.paths.root)
        env[RESOLVED_ENV] = self.shell.encode()
        return env

    def _record(self, spec: StepSpec, step_row: int, result: StepResult) -> None:
        self.control.finish_step(step_row, result.exit_code, result.stderr.strip()[-1000:])
        steps_logger.info(
            "[%s] [%s] %s -> exit code %d (%.2fs)",
            self.run_id, spec.status.value, result.command, result.exit_code, result.duration_s,
        )
        for stream, text in (("stdout", result.stdout), ("stderr", result.stderr)):
            for line in text.splitlines():
                if line.strip():
                    steps_logger.info("[%s] [%s] %s: %s", self.run_id, spec.status.value, stream, line.rstrip())


class Coordinator:
    """Timed poller that runs inside ``python -m estate up``."""

    def __init__(self, paths: EstatePaths, shell: ShellChoice) -> None:
        self.paths = paths
        self.shell = shell
        #: Held while a run executes; ``estate reset`` takes it to reset safely between runs.
        self.run_lock = threading.Lock()
        self.last_poll_at: float | None = None
        self.current_run: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="coordinator", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def poll_interval(self) -> float:
        config = EstateConfig.load(self.paths)
        return float(config.get("poll_interval_seconds", 2.0)) / estate_speed()

    def _loop(self) -> None:
        logger.info("Coordinator polling every %.1fs (shell: %s)", self.poll_interval(), self.shell.label)
        while not self._stop.is_set():
            run_id: str | None = None
            with self.run_lock:
                self.last_poll_at = time.time()
                try:
                    run_id = ControlStore(self.paths.control_db).claim_next_queued()
                    if run_id:
                        self.current_run = run_id
                        self._execute(run_id)
                except Exception:  # noqa: BLE001 - the poller must survive and keep polling
                    logger.exception("Coordinator poll failed")
                finally:
                    self.current_run = None
            if run_id is None:
                self._stop.wait(self.poll_interval())

    def _execute(self, run_id: str) -> None:
        """Run ``run_id`` in a fresh executor process and stream its progress to the console."""
        config = EstateConfig.load(self.paths)
        timeout = float(config.get("run_timeout_seconds", 600))
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(p for p in (str(self.paths.code_root), env.get("PYTHONPATH", "")) if p)
        env["PYTHONIOENCODING"] = "utf-8"
        env["ESTATE_ROOT"] = str(self.paths.root)
        env[RESOLVED_ENV] = self.shell.encode()
        logger.info("Run %s picked up by the coordinator", run_id)
        process = subprocess.Popen(
            [sys.executable, "-m", "estate.coordinator", "execute", "--run-id", run_id],
            cwd=str(self.paths.code_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        watchdog = threading.Timer(timeout, process.kill)
        watchdog.start()
        output_tail: list[str] = []
        try:
            assert process.stdout is not None
            for line in process.stdout:
                text = line.rstrip()
                if text:
                    console_logger.info("  %s", text)
                    output_tail = (output_tail + [text])[-20:]
            exit_code = process.wait()
        finally:
            watchdog.cancel()
        if exit_code != 0:
            logger.error("Run %s executor exited with code %d:\n%s", run_id, exit_code, "\n".join(output_tail))
        self._fail_if_unfinished(run_id, f"Run executor stopped unexpectedly (exit code {exit_code}); see coordinator.log")

    def _fail_if_unfinished(self, run_id: str, reason: str) -> None:
        store = ControlStore(self.paths.control_db)
        run = store.get_run(run_id)
        if run is None or RunStatus(run["status"]).is_terminal:
            return
        store.fail_run(run_id, reason)
        vm_dir = EstateConfig.load(self.paths).vm_dir(run_id)
        if vm_dir.exists():
            rmtree_robust(vm_dir)
            store.add_event(run_id, "VM_DEPROVISIONED", f"VM PAYOUT-VM-{run_id} removed during clean-up")
        logger.error("Run %s FAILED: %s", run_id, reason)


def recover_interrupted_runs(paths: EstatePaths) -> list[str]:
    """Fail runs left in progress by a previous estate process (e.g. stopped with Ctrl+C)."""
    store = ControlStore(paths.control_db)
    config = EstateConfig.load(paths)
    recovered = store.in_progress_runs()
    for run_id in recovered:
        store.fail_run(run_id, "Interrupted: the estate stopped while this run was in progress")
        vm_dir = config.vm_dir(run_id)
        if vm_dir.exists():
            rmtree_robust(vm_dir)
        logger.warning("Run %s was interrupted by a previous shutdown and has been marked FAILED", run_id)
    return recovered


def main(argv: list[str] | None = None) -> int:
    """Entry point for the run executor process."""
    parser = argparse.ArgumentParser(description="Execute one payout run (started by the coordinator).")
    sub = parser.add_subparsers(dest="command", required=True)
    execute = sub.add_parser("execute", help="execute a claimed run")
    execute.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)

    paths = EstatePaths.from_env()
    configure_component("coordinator", paths)
    configure_component("steps", paths, "estate.steps")
    progress = logging.StreamHandler(sys.stdout)
    progress.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(progress)
    RunExecutor(args.run_id, paths, resolve_shell()).execute()
    return 0


if __name__ == "__main__":
    sys.exit(main())
