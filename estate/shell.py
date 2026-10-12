"""Choose how the two file-handling steps run: PowerShell or the Python fallback.

``ESTATE_SHELL`` selects the mode:

* ``auto`` (default): ``pwsh``, then Windows ``powershell``, then the Python fallback. A PowerShell
  candidate is used only if it can actually run a script (execution policy, blocked files, ...).
* ``powershell``: require PowerShell (``pwsh`` preferred); fail loudly if it is unusable.
* ``python``: always use the Python fallback.

On Windows PowerShell is invoked with ``-NoProfile -ExecutionPolicy Bypass -File``.
Both implementations accept the same parameters, print the same messages and use the same exit codes.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from estate.paths import PACKAGE_DIR

SHELL_ENV = "ESTATE_SHELL"
RESOLVED_ENV = "ESTATE_SHELL_RESOLVED"
VALID_MODES = ("auto", "powershell", "python")
PROBE_SCRIPT = PACKAGE_DIR / "powershell" / "Test-EstateShell.ps1"
PROBE_MARKER = "estate-shell-ok"


class ShellUnavailableError(RuntimeError):
    """``ESTATE_SHELL=powershell`` was requested but PowerShell cannot run scripts here."""


@dataclass(frozen=True)
class ShellChoice:
    """The shell used for the PowerShell-backed steps."""

    kind: str  # "pwsh" | "powershell" | "python"
    executable: str
    reason: str

    @property
    def is_powershell(self) -> bool:
        return self.kind in ("pwsh", "powershell")

    @property
    def label(self) -> str:
        return f"{self.kind} ({self.executable})" if self.is_powershell else "python (fallback)"

    def encode(self) -> str:
        return f"{self.kind}|{self.executable}"


def resolve_shell(mode: str | None = None) -> ShellChoice:
    """Resolve the shell for this process (honours a choice already made by ``estate up``)."""
    if mode is None:
        resolved = os.environ.get(RESOLVED_ENV, "").strip()
        if resolved and "|" in resolved:
            kind, executable = resolved.split("|", 1)
            if kind in ("pwsh", "powershell", "python"):
                return ShellChoice(kind, executable, "inherited from the estate process")
        mode = os.environ.get(SHELL_ENV, "auto")
    mode = (mode or "auto").strip().lower()
    if mode not in VALID_MODES:
        raise ShellUnavailableError(f"{SHELL_ENV}={mode!r} is not valid; use one of {', '.join(VALID_MODES)}")
    if mode == "python":
        return ShellChoice("python", sys.executable, f"{SHELL_ENV}=python")

    problems: list[str] = []
    for kind in ("pwsh", "powershell"):
        executable = shutil.which(kind)
        if not executable:
            problems.append(f"{kind}: not found on PATH")
            continue
        usable, detail = probe_powershell(executable)
        if usable:
            return ShellChoice(kind, executable, f"{SHELL_ENV}={mode}: {kind} can run scripts")
        problems.append(f"{kind}: {detail}")

    summary = "; ".join(problems)
    if mode == "powershell":
        raise ShellUnavailableError(f"{SHELL_ENV}=powershell but PowerShell is not usable ({summary})")
    return ShellChoice("python", sys.executable, f"{SHELL_ENV}=auto fell back to Python ({summary})")


def probe_powershell(executable: str, timeout: float = 30.0) -> tuple[bool, str]:
    """Return ``(True, "")`` if ``executable`` can run ``Test-EstateShell.ps1``."""
    command = powershell_command(executable, PROBE_SCRIPT, {})
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not start ({exc})"
    if completed.returncode == 0 and PROBE_MARKER in completed.stdout:
        return True, ""
    # The probe reports language-mode problems on stdout; ignore PowerShell progress noise.
    details = [
        line.strip()
        for line in (completed.stderr + "\n" + completed.stdout).splitlines()
        if line.strip() and not is_clixml_noise(line) and PROBE_MARKER not in line
    ]
    first_error = details[0] if details else "no output"
    return False, f"cannot run scripts (exit code {completed.returncode}: {first_error})"


def is_clixml_noise(line: str) -> bool:
    """True for Windows PowerShell progress records written to a redirected stream.

    Windows PowerShell 5.1 can serialise progress (for example "Preparing modules for first use")
    as ``#< CLIXML`` followed by an ``<Objs ...>`` line. Such lines are never a step's error message.
    """
    stripped = line.strip()
    return stripped.startswith("#< CLIXML") or stripped.startswith("<Objs ")


def powershell_command(executable: str, script: Path, params: Mapping[str, str]) -> list[str]:
    """Build ``<exe> -NoProfile -NonInteractive [-ExecutionPolicy Bypass] -File <script> -Name value ...``."""
    command = [executable, "-NoProfile", "-NonInteractive"]
    if os.name == "nt":
        command += ["-ExecutionPolicy", "Bypass"]
    command += ["-File", str(script)]
    for name, value in params.items():
        command += [f"-{name}", value]
    return command


def python_command(module: str, params: Mapping[str, str], extra_args: tuple[str, ...] = ()) -> list[str]:
    """Build ``python -m <module> [extra] --kebab-name value ...`` (same parameters as the .ps1)."""
    command = [sys.executable, "-m", module, *extra_args]
    for name, value in params.items():
        command += [f"--{_kebab(name)}", value]
    return command


def _kebab(name: str) -> str:
    """``OutboundShare`` -> ``outbound-share``."""
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
