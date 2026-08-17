"""Verify private Phase 1 candidate paths stay outside Git, CI, and static output."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

PRIVATE_MARKERS = (
    "candidate-v7",
    "local-data/phase-1",
    "phase-1-production-inputs-v2.tar",
)


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
    )


def _contains_private_marker(value: str) -> bool:
    normalized = value.replace("\\", "/").lower()
    return any(marker in normalized for marker in PRIVATE_MARKERS)


def check_candidate_isolation(repository_root: Path, build_root: Path) -> dict[str, int]:
    """Return deterministic counts or raise ValueError for an isolation violation."""

    root = repository_root.resolve()
    tracked = _git(root, "ls-files", "-z").stdout.split("\0")
    tracked = [path for path in tracked if path]
    forbidden_tracked = sorted(path for path in tracked if _contains_private_marker(path))
    if forbidden_tracked:
        raise ValueError(f"private candidate path is tracked: {forbidden_tracked}")

    ignore_probes = (
        "local-data/phase-1/local-production-run/candidate-v7/manifest.json",
        "local-data/phase-1/phase-1-production-inputs-v2.tar",
    )
    missing_ignore = [
        path
        for path in ignore_probes
        if _git(root, "check-ignore", "-q", path, check=False).returncode != 0
    ]
    if missing_ignore:
        raise ValueError(f"private candidate path is not ignored: {missing_ignore}")

    workflow_paths = [path for path in tracked if path.startswith(".github/workflows/")]
    workflow_violations: list[str] = []
    for path in workflow_paths:
        content = _git(root, "show", f"HEAD:{path}").stdout
        if _contains_private_marker(content):
            workflow_violations.append(path)
    if workflow_violations:
        raise ValueError(
            "private candidate marker appears in workflow: "
            f"{sorted(workflow_violations)}"
        )

    candidate_build_root = build_root if build_root.is_absolute() else root / build_root
    resolved_build_root = candidate_build_root.resolve()
    try:
        resolved_build_root.relative_to(root)
    except ValueError as exc:
        raise ValueError("build root must stay inside the repository") from exc
    if candidate_build_root.is_symlink():
        raise ValueError("build root must not be a symlink")
    if not resolved_build_root.is_dir():
        raise ValueError("static build root does not exist")

    build_entries = 0
    for directory, names, files in os.walk(resolved_build_root, followlinks=False):
        for name in sorted([*names, *files]):
            path = Path(directory) / name
            relative = path.relative_to(resolved_build_root).as_posix()
            build_entries += 1
            if _contains_private_marker(relative):
                raise ValueError(f"private candidate marker appears in build path: {relative}")
            if path.is_symlink():
                target = os.readlink(path)
                if _contains_private_marker(target):
                    raise ValueError(
                        "private candidate marker appears in build symlink: "
                        f"{relative}"
                    )

    return {
        "trackedPaths": len(tracked),
        "workflowFiles": len(workflow_paths),
        "ignoreProbes": len(ignore_probes),
        "buildEntries": build_entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--build-root", type=Path, default=Path("src/web/dist"))
    arguments = parser.parse_args()
    try:
        summary = check_candidate_isolation(
            arguments.repository_root,
            arguments.build_root,
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
