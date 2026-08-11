#!/usr/bin/env python3
"""Build exact-pinned support/coastal boundary artifacts and immutable evidence."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from searise_pipeline.release.boundary_evidence import (
    build_boundary_evidence_package,
)
from searise_pipeline.release.boundary_pmtiles import BoundaryVectorToolPaths
from searise_pipeline.science import ScienceContractError


def _git(repository: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ScienceContractError(
            f"Cannot establish boundary evidence source revision: {exc}"
        ) from exc
    return completed.stdout.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-contract", type=Path, required=True)
    parser.add_argument("--python-lock", type=Path, required=True)
    parser.add_argument("--tippecanoe", type=Path, required=True)
    parser.add_argument("--tippecanoe-decode", type=Path, required=True)
    parser.add_argument("--pmtiles", type=Path, required=True)
    parser.add_argument("--tippecanoe-source-archive", type=Path, required=True)
    parser.add_argument("--tippecanoe-build-receipt", type=Path, required=True)
    parser.add_argument("--pmtiles-distribution-asset", type=Path, required=True)
    parser.add_argument("--pmtiles-distribution-platform", required=True)
    parser.add_argument("--build-run-id", required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--browser-harness", type=Path, required=True)
    parser.add_argument("--frontend-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    repository = Path(__file__).resolve().parents[2]

    def repository_path(path: Path) -> Path:
        return path if path.is_absolute() else repository / path

    if _git(repository, "status", "--porcelain"):
        raise ScienceContractError(
            "Boundary evidence requires a clean Git worktree"
        )
    source_revision = _git(repository, "rev-parse", "HEAD")
    result = build_boundary_evidence_package(
        args.output,
        repository=repository,
        source_revision=source_revision,
        build_run_id=args.build_run_id,
        release_contract_path=repository_path(args.release_contract),
        python_lock_path=repository_path(args.python_lock),
        tools=BoundaryVectorToolPaths(
            tippecanoe=repository_path(args.tippecanoe),
            decode=repository_path(args.tippecanoe_decode),
            pmtiles=repository_path(args.pmtiles),
            tippecanoe_source=repository_path(args.tippecanoe_source_archive),
            tippecanoe_build_receipt=repository_path(
                args.tippecanoe_build_receipt
            ),
            pmtiles_distribution_asset=repository_path(
                args.pmtiles_distribution_asset
            ),
            platform=args.pmtiles_distribution_platform,
        ),
        node_path=repository_path(args.node),
        browser_harness_path=repository_path(args.browser_harness),
        frontend_directory=repository_path(args.frontend_directory),
    )
    print(result)


if __name__ == "__main__":
    main()
