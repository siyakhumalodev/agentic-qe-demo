"""One-time setup for the demo kit (Windows, macOS and Linux).

    python scripts/setup.py                     full setup
    python scripts/setup.py --ado-org <org>     ...and add the remote Azure DevOps MCP server (preview)
    python scripts/setup.py --ado-local <org>   ...and add the local Azure DevOps MCP server (npx)
    python scripts/setup.py --dry-run           show every step, change nothing

Steps: check Python -> create .venv -> install requirements -> install Playwright Chromium ->
write .vscode/mcp.json (venv interpreter for this OS) -> initialise the estate -> check tools ->
smoke test (pytest tests/unit tests/bdd).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = REPO_ROOT / ".venv"
MCP_JSON = REPO_ROOT / ".vscode" / "mcp.json"
MIN_PYTHON = (3, 11)
IS_WINDOWS = os.name == "nt"


class SetupError(RuntimeError):
    """A setup step failed in a way the user must fix."""


class Setup:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.dry_run: bool = args.dry_run
        self.warnings: list[str] = []
        self.step_no = 0
        self.total_steps = 8

    # -- helpers --------------------------------------------------------------------------------

    def step(self, title: str) -> None:
        self.step_no += 1
        print(f"\n[{self.step_no}/{self.total_steps}] {title}", flush=True)

    def run(self, command: list[str], *, fatal: bool = True, hint: str = "", quiet: bool = False) -> bool:
        printable = " ".join(f'"{part}"' if " " in part else part for part in command)
        print(f"  $ {printable}", flush=True)
        if self.dry_run:
            return True
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            capture_output=quiet,
            text=True,
        )
        if result.returncode == 0:
            return True
        message = f"Command failed (exit code {result.returncode}): {printable}"
        if quiet and result.stderr:
            message += "\n    " + "\n    ".join(result.stderr.strip().splitlines()[-5:])
        if hint:
            message += f"\n    Hint: {hint}"
        if fatal:
            raise SetupError(message)
        self.warnings.append(message)
        print(f"  WARNING: {message}", flush=True)
        return False

    @property
    def python(self) -> str:
        if self.args.use_current_python:
            return sys.executable
        if IS_WINDOWS:
            return str(VENV_DIR / "Scripts" / "python.exe")
        return str(VENV_DIR / "bin" / "python")

    # -- steps ----------------------------------------------------------------------------------

    def check_python(self) -> None:
        self.step("Check Python")
        version = sys.version_info
        print(f"  Python {platform.python_version()} at {sys.executable}")
        if version < MIN_PYTHON:
            raise SetupError(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required; found {platform.python_version()}. "
                             "Install a newer Python from python.org and run this script with it.")

    def create_venv(self) -> None:
        self.step("Create the virtual environment (.venv)")
        if self.args.use_current_python:
            print("  Skipped (--use-current-python): using the current interpreter.")
            return
        if Path(self.python).exists():
            print(f"  Reusing {VENV_DIR.relative_to(REPO_ROOT)}")
            return
        self.run([sys.executable, "-m", "venv", str(VENV_DIR)])

    def install_requirements(self) -> None:
        self.step("Install Python dependencies (requirements.txt)")
        if self.args.skip_install:
            print("  Skipped (--skip-install).")
            return
        self.run([self.python, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"],
                 fatal=False, quiet=True)
        self.run(
            [self.python, "-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"],
            hint="Behind a proxy? Set HTTPS_PROXY (or PIP_INDEX_URL for an internal mirror) and re-run.",
        )

    def install_browsers(self) -> None:
        self.step("Install Playwright Chromium (for pytest-playwright)")
        if self.args.skip_install or self.args.skip_browsers:
            print("  Skipped.")
            return
        self.run(
            [self.python, "-m", "playwright", "install", "chromium"],
            fatal=False,
            hint="If the download is blocked, run the browser tests with an installed browser instead: "
                 "pytest tests/e2e -m e2e --browser-channel msedge   (or --browser-channel chrome)",
        )

    def write_mcp_json(self) -> None:
        self.step("Write .vscode/mcp.json (MCP servers for VS Code)")
        existing: dict[str, Any] = {}
        if MCP_JSON.exists():
            try:
                existing = json.loads(MCP_JSON.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                backup = MCP_JSON.with_suffix(".json.bak")
                print(f"  Existing file is not plain JSON (comments?) - backing it up to {backup.name}")
                if not self.dry_run:
                    shutil.copyfile(MCP_JSON, backup)
        servers: dict[str, Any] = dict(existing.get("servers", {}))
        servers["estate"] = {
            "type": "stdio",
            "command": self._mcp_interpreter(),
            "args": ["-m", "mcp_servers.estate.server"],
            "cwd": "${workspaceFolder}",
            "env": {"PYTHONPATH": "${workspaceFolder}", "PYTHONIOENCODING": "utf-8"},
        }
        servers["playwright"] = {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@playwright/mcp@latest", *self._playwright_browser_args()],
        }
        if self.args.ado_org:
            servers["ado-remote"] = {"type": "http", "url": f"https://mcp.dev.azure.com/{self.args.ado_org}"}
        if self.args.ado_local:
            servers["ado"] = {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@azure-devops/mcp", self.args.ado_local, "-d", "core", "work", "work-items", "test-plans"],
            }
        document = {"servers": servers, "inputs": existing.get("inputs", [])}
        print(f"  Servers: {', '.join(servers)}")
        if not self.dry_run:
            MCP_JSON.parent.mkdir(parents=True, exist_ok=True)
            MCP_JSON.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        print(f"  Wrote {MCP_JSON.relative_to(REPO_ROOT).as_posix()}{' (dry run - not written)' if self.dry_run else ''}")

    def init_estate(self) -> None:
        self.step("Initialise the estate (runtime folders, databases; patch drift OFF)")
        if IS_WINDOWS:
            self._unblock_powershell_scripts()
        self.run([self.python, "-m", "estate", "patch-drift", "off"], quiet=True)
        self.run([self.python, "-m", "estate", "reset"])

    def check_tools(self) -> None:
        self.step("Check optional tools (PowerShell, Node.js for the Playwright MCP server, git)")
        self.run([self.python, "-c", "from estate.shell import resolve_shell; c = resolve_shell(); "
                  "print('  Estate shell:', c.label); print('  ', c.reason)"], fatal=False)
        node = shutil.which("node")
        npx = shutil.which("npx")
        if node and npx:
            version = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout.strip()
            major = int(re.sub(r"[^0-9.]", "", version).split(".")[0] or 0)
            print(f"  Node.js {version} and npx found.")
            if major < 20:
                self.warnings.append(f"Node.js {version} found; the Playwright MCP server needs Node.js 20+.")
        else:
            self.warnings.append("Node.js/npx not found: install Node.js 20+ LTS to use the Playwright MCP server.")
        if shutil.which("git"):
            tag = subprocess.run(["git", "tag", "--list", "demo-baseline"], cwd=REPO_ROOT, capture_output=True,
                                 text=True, check=False).stdout.strip()
            if tag:
                print("  git tag demo-baseline found (python scripts/reset_demo.py will work).")
            else:
                self.warnings.append("git tag 'demo-baseline' not found: reset_demo.py needs it "
                                     "(unzip the kit with its .git folder, or run: git tag demo-baseline).")
        else:
            self.warnings.append("git not found: install Git to use python scripts/reset_demo.py.")

    def smoke_test(self) -> None:
        self.step("Smoke test (pytest tests/unit tests/bdd)")
        if self.args.skip_smoke:
            print("  Skipped (--skip-smoke).")
            return
        self.run([self.python, "-m", "pytest", "tests/unit", "tests/bdd", "-q", "-p", "no:cacheprovider"],
                 hint="Run the same command yourself to see the failure in full.")

    # -- internals ------------------------------------------------------------------------------

    def _mcp_interpreter(self) -> str:
        if self.args.use_current_python:
            return sys.executable
        if IS_WINDOWS:
            return "${workspaceFolder}\\.venv\\Scripts\\python.exe"
        return "${workspaceFolder}/.venv/bin/python"

    def _playwright_browser_args(self) -> list[str]:
        choice = self.args.playwright_browser
        if choice == "auto":
            if _chrome_installed():
                return []  # Playwright MCP uses Chrome by default
            if _edge_installed():
                print("  Google Chrome not found; the Playwright MCP server will use Microsoft Edge.")
                return ["--browser", "msedge"]
            self.warnings.append("Neither Chrome nor Edge was found for the Playwright MCP server; install Chrome or "
                                 "run: npx playwright install chrome")
            return []
        return [] if choice == "chrome" else ["--browser", choice]

    def _unblock_powershell_scripts(self) -> None:
        """Remove the 'downloaded from the internet' mark so execution policy does not block the scripts."""
        for script in sorted((REPO_ROOT / "estate" / "powershell").glob("*.ps1")):
            stream = f"{script}:Zone.Identifier"
            if self.dry_run:
                print(f"  would unblock {script.name}")
                continue
            try:
                os.remove(stream)
                print(f"  Unblocked {script.name}")
            except OSError:
                pass  # not blocked

    def summary(self) -> None:
        activate = r".venv\Scripts\Activate.ps1" if IS_WINDOWS else "source .venv/bin/activate"
        print("\nSetup complete." if not self.warnings else "\nSetup complete, with warnings:")
        for warning in self.warnings:
            print(f"  - {warning}")
        print("\nNext steps:")
        print(f"  1. Activate the virtual environment:  {activate}")
        if IS_WINDOWS:
            print("     (if PowerShell blocks it: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass)")
        print("  2. Start the estate in its own terminal:  python -m estate up")
        print("  3. Open the portal:  http://localhost:8085")
        print("  4. In VS Code: open the MCP servers view and start 'estate' and 'playwright';")
        print("     in Chat set the session target to Local and pick the QE Orchestrator agent.")
        print("  See docs/REHEARSAL-CHECKLIST.md before a live session.")


def _chrome_installed() -> bool:
    if IS_WINDOWS:
        roots = [os.environ.get(name, "") for name in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData")]
        return any(root and Path(root, "Google", "Chrome", "Application", "chrome.exe").exists() for root in roots)
    if sys.platform == "darwin":
        return Path("/Applications/Google Chrome.app").exists()
    return bool(shutil.which("google-chrome") or shutil.which("google-chrome-stable"))


def _edge_installed() -> bool:
    if IS_WINDOWS:
        roots = [os.environ.get(name, "") for name in ("ProgramFiles", "ProgramFiles(x86)")]
        return any(root and Path(root, "Microsoft", "Edge", "Application", "msedge.exe").exists() for root in roots)
    if sys.platform == "darwin":
        return Path("/Applications/Microsoft Edge.app").exists()
    return bool(shutil.which("microsoft-edge") or shutil.which("microsoft-edge-stable"))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace", line_buffering=True)
    parser = argparse.ArgumentParser(description="One-time setup for the agentic QE demo kit.")
    parser.add_argument("--ado-org", metavar="ORG", help="add the remote Azure DevOps MCP server for this organisation")
    parser.add_argument("--ado-local", metavar="ORG", help="add the local Azure DevOps MCP server (npx) for this org")
    parser.add_argument("--playwright-browser", choices=("auto", "chrome", "msedge"), default="auto",
                        help="browser for the Playwright MCP server (default: Chrome if installed, else Edge)")
    parser.add_argument("--skip-install", action="store_true", help="do not pip install or download browsers")
    parser.add_argument("--skip-browsers", action="store_true", help="do not download Playwright Chromium")
    parser.add_argument("--skip-smoke", action="store_true", help="do not run the smoke test")
    parser.add_argument("--use-current-python", action="store_true",
                        help="use this interpreter instead of creating .venv (CI, or dependencies already installed)")
    parser.add_argument("--dry-run", action="store_true", help="print the steps without changing anything")
    args = parser.parse_args(argv)

    setup = Setup(args)
    print(f"Agentic QE demo kit setup ({platform.system()} {platform.machine()}){' - DRY RUN' if args.dry_run else ''}")
    try:
        setup.check_python()
        setup.create_venv()
        setup.install_requirements()
        setup.install_browsers()
        setup.write_mcp_json()
        setup.init_estate()
        setup.check_tools()
        setup.smoke_test()
    except SetupError as exc:
        print(f"\nSETUP FAILED: {exc}", file=sys.stderr)
        return 1
    setup.summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
