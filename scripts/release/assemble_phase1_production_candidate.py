#!/usr/bin/env python3
"""Assemble and validate one exact real-source Phase 1 candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from searise_pipeline.candidate_completeness.production_assembler import (
    ProductionCandidateMetadata,
    assemble_production_candidate,
)
from searise_pipeline.candidate_completeness.production_binary_validators import (
    BoundaryQaAuthority,
    ProductionBinaryQaAuthorities,
    ProjectionQaAuthority,
    SettlementQaAuthority,
)
from searise_pipeline.candidate_completeness.production_validators import (
    ProductionQaAuthorities,
    production_validator_dispatcher,
)
from searise_pipeline.release import BoundaryVectorToolPaths, load_source_fixture

BROTLI_LINUX_X86_64_SHA256 = (
    "01969d4716e4ecc585ab1302e0a0d4e0fa9619017ab17409a54173dac5fbacef"
)


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON authority must be an object: {path}")
    return value


def _tools(args: argparse.Namespace) -> BoundaryVectorToolPaths:
    return BoundaryVectorToolPaths(
        tippecanoe=args.toolchain_root / "tippecanoe",
        decode=args.toolchain_root / "tippecanoe-decode",
        pmtiles=args.toolchain_root / "pmtiles",
        tippecanoe_source=args.toolchain_root / "tippecanoe-2.79.0.tar.gz",
        tippecanoe_build_receipt=args.tippecanoe_build_receipt,
        pmtiles_distribution_asset=(
            args.toolchain_root / "go-pmtiles_1.31.2_Linux_x86_64.tar.gz"
        ),
        platform="linux-x86_64",
    )


def _dispatcher(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    contract = _json(args.release_contract)
    source = load_source_fixture(
        args.source_fixture,
        receipt=_json(args.source_fixture_receipt),
        release_contract=contract,
    )
    tools = _tools(args)
    binary = ProductionBinaryQaAuthorities(
        projection=ProjectionQaAuthority(
            source=source,
            contract=contract,
            tippecanoe=tools.tippecanoe,
            decode=tools.decode,
            pmtiles=tools.pmtiles,
            tippecanoe_source=tools.tippecanoe_source,
            tippecanoe_build_receipt=tools.tippecanoe_build_receipt,
            pmtiles_distribution_asset=tools.pmtiles_distribution_asset,
            platform=tools.platform,
        ),
        boundary=BoundaryQaAuthority(
            contract=contract,
            support_geojson=args.support_geojson,
            coastal_geojson=args.coastal_geojson,
            tools=tools,
        ),
        settlement=SettlementQaAuthority(
            spatial_receipt=args.authority_root
            / "geonames-spatial-stage-v1.receipt.json",
            artifact_receipt=args.authority_root / "settlements.receipt.json",
            work_directory=args.work_root / "settlement",
        ),
    )
    return production_validator_dispatcher(
        ProductionQaAuthorities(
            binary=binary,
            brotli=args.toolchain_root / "brotli",
            brotli_sha256=BROTLI_LINUX_X86_64_SHA256,
            work_directory=args.work_root / "search",
        )
    )


def assemble(args: argparse.Namespace) -> dict[str, object]:
    args.work_root.mkdir(mode=0o700)
    (args.work_root / "settlement").mkdir(mode=0o700)
    (args.work_root / "search").mkdir(mode=0o700)
    dispatcher = _dispatcher(args)
    summary = assemble_production_candidate(
        args.input_root,
        args.output,
        ProductionCandidateMetadata(
            candidate_id=args.candidate_id,
            data_release_id=args.data_release_id,
            generated_at=args.generated_at,
        ),
        dispatcher,
    )
    return {
        "candidateId": summary.candidate_id,
        "artifactCount": summary.artifact_count,
        "artifactBytes": summary.artifact_bytes,
        "manifestSha256": summary.manifest_sha256,
        "output": str(summary.output_directory),
    }


def _parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--authority-root", type=Path, required=True)
    parser.add_argument("--toolchain-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--data-release-id", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--release-contract",
        type=Path,
        default=root / "src/pipeline/science/ar6-regional-release.json",
    )
    parser.add_argument(
        "--source-fixture",
        type=Path,
        default=root / "src/pipeline/fixtures/ar6-regional-release/source-fixture.json.gz",
    )
    parser.add_argument(
        "--source-fixture-receipt",
        type=Path,
        default=(
            root
            / "src/pipeline/fixtures/ar6-regional-release/source-fixture-receipt.json"
        ),
    )
    parser.add_argument(
        "--tippecanoe-build-receipt",
        type=Path,
        default=root / "src/pipeline/toolchain/tippecanoe-linux-x86_64-build-receipt.json",
    )
    parser.add_argument(
        "--support-geojson",
        type=Path,
        default=root / "data/geometry/europe.geojson",
    )
    parser.add_argument(
        "--coastal-geojson",
        type=Path,
        default=root / "data/geometry/coastal_analysis_zone.geojson",
    )
    return parser


def main() -> int:
    print(json.dumps(assemble(_parser().parse_args()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
