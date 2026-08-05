#!/usr/bin/env python3
"""Build the complete issue #110 candidate or emit an explicit blocked gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from searise_pipeline.release import (
    build_regional_release,
    build_source_from_verified_archive,
    load_release_contract,
    load_source_fixture,
)
from searise_pipeline.release.evidence import (
    candidate_binding,
    ensure_outside_candidate,
    write_new_json_record,
)
from searise_pipeline.science import ScienceContractError


def _load(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
            f"Cannot establish the exact release source revision: {exc}"
        ) from exc
    return completed.stdout.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path)
    source.add_argument("--fixture", type=Path)
    parser.add_argument("--fixture-receipt", type=Path)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--source-semantics", type=Path, required=True)
    parser.add_argument("--release-contract", type=Path, required=True)
    parser.add_argument("--lookup-goldens", type=Path, required=True)
    parser.add_argument("--tippecanoe", type=Path, required=True)
    parser.add_argument("--tippecanoe-decode", type=Path, required=True)
    parser.add_argument("--pmtiles", type=Path, required=True)
    parser.add_argument("--tippecanoe-source-archive", type=Path, required=True)
    parser.add_argument("--tippecanoe-build-receipt", type=Path, required=True)
    parser.add_argument("--pmtiles-distribution-asset", type=Path, required=True)
    parser.add_argument("--pmtiles-distribution-platform", required=True)
    parser.add_argument("--python-lock", type=Path, required=True)
    parser.add_argument("--build-environment-id", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--failure-gate", type=Path, required=True)
    parser.add_argument("--timing-evidence", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    workflow_started = time.perf_counter()
    ensure_outside_candidate(
        args.output,
        args.failure_gate,
        label="Failure gate",
        require_new=True,
    )
    ensure_outside_candidate(
        args.output,
        args.timing_evidence,
        label="Build timing evidence",
        require_new=True,
    )
    if args.failure_gate.resolve(strict=False) == args.timing_evidence.resolve(strict=False):
        raise ScienceContractError("Failure and timing evidence paths must be distinct")
    try:
        repository = Path(__file__).resolve().parents[2]
        if _git(repository, "status", "--porcelain"):
            raise ScienceContractError(
                "Release candidates require a clean Git worktree"
            )
        source_revision = _git(repository, "rev-parse", "HEAD")
        contract = load_release_contract(args.release_contract)
        if args.archive:
            regional_source = build_source_from_verified_archive(
                args.archive,
                source_lock=_load(args.source_lock),
                source_semantics=_load(args.source_semantics),
                release_contract=contract,
                release_contract_path=args.release_contract,
            )
        else:
            if args.fixture_receipt is None:
                raise ScienceContractError("Fixture builds require --fixture-receipt")
            regional_source = load_source_fixture(
                args.fixture,
                receipt=_load(args.fixture_receipt),
                release_contract=contract,
            )
        result = build_regional_release(
            regional_source,
            args.output,
            release_id=args.release_id,
            contract=contract,
            tippecanoe_path=args.tippecanoe,
            decode_path=args.tippecanoe_decode,
            pmtiles_path=args.pmtiles,
            tippecanoe_source_archive_path=args.tippecanoe_source_archive,
            tippecanoe_build_receipt_path=args.tippecanoe_build_receipt,
            pmtiles_distribution_asset_path=args.pmtiles_distribution_asset,
            pmtiles_distribution_platform=args.pmtiles_distribution_platform,
            python_lock_path=args.python_lock,
            lookup_goldens_path=args.lookup_goldens,
            build_environment_id=args.build_environment_id,
            source_revision=source_revision,
            workflow_started_monotonic=workflow_started,
        )
        write_new_json_record(
            args.timing_evidence,
            {
                "schemaVersion": 1,
                "candidate": candidate_binding(result.output_directory),
                "timer": "python-time-perf-counter",
                "startedBeforeSourceVerification": True,
                "endedAfterAtomicCandidatePublish": True,
                "fullCleanBuildDurationSeconds": result.build_duration_seconds,
            },
        )
    except (OSError, KeyError, ValueError, ScienceContractError) as exc:
        blocked = {
            "schemaVersion": 1,
            "gateId": "phase-0r-ar6-regional-release-v1",
            "issue": 110,
            "releaseId": args.release_id,
            "scientificDisposition": "projection-only",
            "automatedValidation": "failed",
            "releaseDisposition": "pending-owner",
            "phase1Unlocked": False,
            "blockingChecks": ["preflight"],
            "fallback": "do-not-publish-or-unlock-phase-1",
            "failure": {"type": type(exc).__name__, "message": str(exc)},
            "emittedScientificArtifacts": [],
        }
        write_new_json_record(args.failure_gate, blocked)
        raise SystemExit(1) from exc
    print(
        json.dumps(
            {
                "output": str(result.output_directory),
                "durationSeconds": result.build_duration_seconds,
                "gate": result.gate,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
