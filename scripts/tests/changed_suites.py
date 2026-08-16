"""Select fast feedback commands from versioned changed-path ownership."""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from scripts.tests.validate_test_inventory import DEFAULT_INVENTORY, load_inventory
except ModuleNotFoundError:  # Support direct execution as well as ``python -m``.
    from validate_test_inventory import DEFAULT_INVENTORY, load_inventory

ROOT = Path(__file__).resolve().parents[2]


def path_matches(path: str, pattern: str) -> bool:
    """Match normalized repository paths against inventory glob patterns."""
    return fnmatch.fnmatchcase(path.replace("\\", "/"), pattern.replace("\\", "/"))


def select_suites(
    inventory: dict[str, Any], changed_paths: Sequence[str]
) -> list[dict[str, Any]]:
    selected = []
    for suite in inventory["suites"]:
        if suite.get("status") != "active":
            continue
        if any(
            path_matches(path, pattern)
            for path in changed_paths
            for pattern in suite["changedPaths"]
        ):
            selected.append(suite)
    return sorted(selected, key=lambda suite: suite["id"])


def fast_local_suites(suites: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only credential-free fast suites with an executable focused command."""
    return [
        suite
        for suite in suites
        if suite.get("status") == "active"
        and suite["execution"]["tier"] == "fast"
        and not suite["execution"]["requiresDocker"]
        and not suite["execution"]["requiresCredentials"]
        and suite["commands"]["focused"] is not None
    ]


def _git_changed_paths(base_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _run_commands(suites: Sequence[dict[str, Any]]) -> int:
    commands_seen: set[str] = set()
    for suite in suites:
        if suite.get("status") != "active":
            continue
        command = suite["commands"]["focused"]
        if command in commands_seen:
            continue
        commands_seen.add(command)
        print(f"RUN {suite['id']}: {command}", flush=True)
        result = subprocess.run(command, cwd=ROOT, shell=True, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--changed", nargs="+", help="Explicit repository-relative paths")
    source.add_argument("--base-ref", help="Select paths changed from BASE_REF...HEAD")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--all-tiers", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    changed_paths = args.changed or _git_changed_paths(args.base_ref)
    suites = select_suites(load_inventory(args.inventory), changed_paths)
    if not args.all_tiers:
        suites = fast_local_suites(suites)

    for suite in suites:
        command = suite["commands"]["focused"] or "CI only"
        print(f"{suite['id']} [{suite['execution']['tier']}]: {command}")
    if not suites:
        print("No inventoried suites match the changed paths.")
        return 0
    return _run_commands(suites) if args.run else 0


if __name__ == "__main__":
    raise SystemExit(main())
