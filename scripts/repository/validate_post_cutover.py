"""Preserve completed removal authority while current application files evolve.

ADR-027 scopes the unchanged issue-71 validator to the completed receipt. This
adapter additionally checks current committed and working-tree safeguards.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

COMPLETED_RECEIPT_COMMIT = "fd38eddccb5dce6405df48a8f25c045e740efdca"
CONTRACTS = "contracts/repository-removal/v2"
STAGES = (CONTRACTS, f"{CONTRACTS}/issue-70", f"{CONTRACTS}/issue-71")
VALIDATOR = "scripts/repository/validate_issue71_removal.py"
REMOVED_DIRECTORIES = ("src/api", "src/frontend", "infra/db", "infra/blob-seed")


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "--no-replace-objects", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1"},
    )
    return result.stdout


def regular_path(root: Path, logical: str) -> Path:
    if (
        not logical
        or logical.startswith("/")
        or "\\" in logical
        or any(part in ("", ".", "..") for part in logical.split("/"))
    ):
        raise ValueError(f"Invalid authority path: {logical}")
    path = root
    for part in logical.split("/"):
        path = path / part
        if path.is_symlink():
            raise ValueError(f"Authority path uses a symlink: {logical}")
    if not path.is_file():
        raise ValueError(f"Authority is not a regular file: {logical}")
    return path


def read_json(root: Path, commit: str, path: str) -> dict:
    return json.loads(git(root, "show", f"{commit}:{path}"))


def completed_boundary(root: Path, anchor: str) -> tuple[set[str], set[str]]:
    """Derive authority and removed files from the fixed, reviewed Git history."""
    authorities: set[str] = set()
    removed: set[str] = set()
    for stage in STAGES:
        for name in (
            "preapproval",
            "owner-decision",
            "removal-plan",
            "application-receipt",
        ):
            authorities.add(f"{stage}/{name}.json")
        preapproval = read_json(root, anchor, f"{stage}/preapproval.json")
        authorities.update(preapproval["trustRoots"].values())
        plan = read_json(root, anchor, f"{stage}/removal-plan.json")
        removed.update(
            entry["path"]
            for entry in plan["entries"]
            if entry["after"]["state"] == "absent"
        )
    return authorities, removed


def validate_current_state(
    root: Path, head: str, *, anchor: str = COMPLETED_RECEIPT_COMMIT
) -> None:
    git(root, "merge-base", "--is-ancestor", anchor, head)
    authorities, removed = completed_boundary(root, anchor)
    for path in sorted(authorities):
        expected_entry = git(root, "ls-tree", anchor, "--", path)
        if not expected_entry.startswith((b"100644 blob ", b"100755 blob ")):
            raise ValueError(f"Historical authority is not a regular Git blob: {path}")
        if git(root, "ls-tree", head, "--", path) != expected_entry:
            raise ValueError(f"Committed historical authority changed: {path}")
        current = regular_path(root, path)
        expected = git(root, "show", f"{anchor}:{path}")
        if current.read_bytes() != expected:
            raise ValueError(f"Working historical authority changed: {path}")
        executable = bool(current.stat().st_mode & 0o111)
        if executable != expected_entry.startswith(b"100755 "):
            raise ValueError(f"Historical authority mode changed: {path}")
    for path in sorted(removed | set(REMOVED_DIRECTORIES)):
        if git(root, "ls-tree", head, "--", path) or os.path.lexists(root / path):
            raise ValueError(f"Removed runtime path was restored: {path}")


def validate_post_cutover(root: Path, head: str) -> None:
    validate_current_state(root, head)
    # The original validator still independently checks exact P/D/A/R history,
    # original owner-comment authority, schemas, hashes and planned post-state.
    # Retained application files after R are governed by current quality gates.
    subprocess.run(
        [
            sys.executable,
            str(root / VALIDATOR),
            "--repository-root",
            str(root),
            "post-application",
            "--receipt-commit",
            COMPLETED_RECEIPT_COMMIT,
            "--head-commit",
            COMPLETED_RECEIPT_COMMIT,
            "--verify-owner-comment",
        ],
        cwd=root,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--head-commit", default="HEAD")
    parser.add_argument("--verify-owner-comment", action="store_true", required=True)
    args = parser.parse_args()
    try:
        validate_post_cutover(args.repository_root.resolve(), args.head_commit)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Post-cutover validation failed: {error}", file=sys.stderr)
        return 1
    print("Validated completed removal history and current post-cutover safeguards.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
