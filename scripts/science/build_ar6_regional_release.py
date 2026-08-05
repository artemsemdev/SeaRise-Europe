#!/usr/bin/env python3
"""Build the complete issue #110 candidate or emit an explicit blocked gate."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from searise_pipeline.release import (
    build_regional_release,
    build_source_from_verified_archive,
    load_release_contract,
    load_source_fixture,
)
from searise_pipeline.science import ScienceContractError


def _load(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


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
    parser.add_argument("--python-lock", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reproducibility-report", type=Path)
    parser.add_argument("--delivery-report", type=Path)
    parser.add_argument(
        "--owner-decision",
        choices=("pending-owner", "approved", "rejected"),
        default="pending-owner",
    )
    parser.add_argument("--failure-gate", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
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
            python_lock_path=args.python_lock,
            lookup_goldens_path=args.lookup_goldens,
            reproducibility_report=(
                _load(args.reproducibility_report)
                if args.reproducibility_report
                else None
            ),
            delivery_report=_load(args.delivery_report)
            if args.delivery_report
            else None,
            owner_decision=args.owner_decision,
        )
    except (OSError, KeyError, ValueError, ScienceContractError) as exc:
        blocked = {
            "schemaVersion": 1,
            "gateId": "phase-0r-ar6-regional-release-v1",
            "issue": 110,
            "disposition": "blocked",
            "releaseDecision": "pending-owner",
            "phase1Unlocked": False,
            "blockingChecks": ["preflight"],
            "failure": {"type": type(exc).__name__, "message": str(exc)},
            "emittedScientificArtifacts": [],
        }
        _write_json(args.failure_gate, blocked)
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
