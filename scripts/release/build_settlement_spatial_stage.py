#!/usr/bin/env python3
"""Build and immutably publish one verified settlement spatial-stage pair."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from searise_pipeline.settlements.spatial_classification import (
    SpatialClassificationError,
    production_geometry_bindings,
)
from searise_pipeline.settlements.spatial_classification_stage import SpatialAssetInputs
from searise_pipeline.settlements.spatial_stage_runner import (
    SpatialStageRunnerError,
    build_spatial_stage,
)
from searise_pipeline.settlements.spatial_toolchain import (
    SpatialToolchainError,
    load_spatial_manifest,
    verify_spatial_toolchain,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue-db", type=Path, required=True)
    parser.add_argument("--catalogue-receipt", type=Path, required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--spatial-cache-root", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--toolchain-manifest", type=Path, required=True)
    parser.add_argument(
        "--platform", choices=("linux-x86_64", "macos-arm64"), required=True
    )
    parser.add_argument(
        "--geometry-profile", choices=("production-reviewed",), required=True
    )
    args = parser.parse_args(argv)
    try:
        manifest = load_spatial_manifest(args.toolchain_manifest)
        evidence = verify_spatial_toolchain(
            args.spatial_cache_root, manifest, platform_key=args.platform
        )
        inputs = SpatialAssetInputs(
            args.repository_root,
            args.spatial_cache_root,
            args.work_dir,
            args.toolchain_manifest,
            evidence,
            production_geometry_bindings(args.repository_root),
        )
        receipt = build_spatial_stage(
            args.catalogue_db,
            args.catalogue_receipt,
            args.output_db,
            args.output_receipt,
            asset_inputs=inputs,
        )
    except (
        SpatialClassificationError,
        SpatialStageRunnerError,
        SpatialToolchainError,
    ) as exc:
        parser.error(str(exc))
    print(receipt["deterministicIdentity"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
