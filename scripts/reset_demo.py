"""Reset code and data to the demo baseline between rehearsals.

    python scripts/reset_demo.py          (asks for confirmation)
    python scripts/reset_demo.py --yes    (no prompt)

1. ``git reset --hard demo-baseline`` and ``git clean -fd`` - discards every change since the
   baseline tag (agent edits, applied fallbacks, generated reports). Ignored files such as
   ``.venv/``, ``runtime/`` and ``.vscode/mcp.json`` are kept.
2. ``python -m estate patch-drift off`` - the baseline has no simulated patch.
3. ``python -m estate reset`` - clears runs, results, shares, VMs and logs (safe while the estate
   is running; a running estate picks up the restored code on the next run).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TAG = "demo-baseline"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=check)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace", line_buffering=True)
    parser = argparse.ArgumentParser(description="Reset code + data to the demo baseline.")
    parser.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--tag", default=TAG, help=f"git tag to restore (default: {TAG})")
    args = parser.parse_args(argv)

    try:
        git("rev-parse", "--is-inside-work-tree")
    except (OSError, subprocess.CalledProcessError):
        print("This folder is not a git repository (or git is not installed). Unzip the kit with its .git folder.",
              file=sys.stderr)
        return 1
    if git("rev-parse", "-q", "--verify", f"refs/tags/{args.tag}", check=False).returncode != 0:
        print(f"Tag '{args.tag}' not found. Create it on the clean baseline with: git tag {args.tag}", file=sys.stderr)
        return 1

    changes = [line for line in git("status", "--porcelain").stdout.splitlines() if line.strip()]
    ahead = git("rev-list", "--count", f"{args.tag}..HEAD").stdout.strip()
    print(f"Resetting code to '{args.tag}': {len(changes)} changed/untracked path(s), {ahead} commit(s) since the tag.")
    for line in changes[:15]:
        print(f"  {line}")
    if len(changes) > 15:
        print(f"  ... and {len(changes) - 15} more")

    if not args.yes:
        if not sys.stdin.isatty():
            print("Not running interactively; re-run with --yes to confirm.", file=sys.stderr)
            return 1
        answer = input("Discard all of these changes? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return 1

    git("reset", "--hard", args.tag)
    git("clean", "-fd")
    print(f"Code restored to '{args.tag}'.")

    for command in (["patch-drift", "off"], ["reset"]):
        result = subprocess.run([sys.executable, "-m", "estate", *command], cwd=REPO_ROOT, check=False)
        if result.returncode != 0:
            print(f"'python -m estate {' '.join(command)}' failed (exit code {result.returncode}).", file=sys.stderr)
            return result.returncode
    print("\nBaseline restored. Patch drift is OFF and the estate data is empty.")
    print("If the estate is running it uses the restored code from the next payout run (no restart needed,")
    print("unless estate/portal.py or estate/cli.py changed - then restart python -m estate up).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
