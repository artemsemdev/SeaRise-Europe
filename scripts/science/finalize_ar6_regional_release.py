#!/usr/bin/env python3
"""Finalize automated issue #110 evidence without exercising owner authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from searise_pipeline.release import finalize_recovery_gate, load_release_contract
from searise_pipeline.release.evidence import (
    ensure_outside_candidate,
    write_new_json_record,
)
from searise_pipeline.science import ScienceContractError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--release-contract", type=Path, required=True)
    parser.add_argument("--reproducibility-report", type=Path, required=True)
    parser.add_argument("--delivery-trace", type=Path, required=True)
    parser.add_argument("--build-timing", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--failure-gate", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.candidate.is_symlink():
        raise ScienceContractError("Release candidate path cannot be a symlink")
    candidate = args.candidate.resolve(strict=False)
    output = ensure_outside_candidate(
        candidate,
        args.output,
        label="Finalized automated gate",
        require_new=True,
    )
    failure_gate = ensure_outside_candidate(
        candidate,
        args.failure_gate,
        label="Finalization failure gate",
        require_new=True,
    )
    if output == failure_gate:
        raise ScienceContractError("Output and failure gate paths must be distinct")
    try:
        gate = finalize_recovery_gate(
            candidate,
            contract=load_release_contract(args.release_contract),
            reproducibility_report_path=args.reproducibility_report,
            delivery_trace_path=args.delivery_trace,
            build_timing_path=args.build_timing,
            harness_path=args.harness,
            repository_root=args.repository_root,
        )
        write_new_json_record(output, gate)
    except (OSError, KeyError, TypeError, ValueError, ScienceContractError) as exc:
        write_new_json_record(
            failure_gate,
            {
                "schemaVersion": 1,
                "gateId": "phase-0r-ar6-regional-release-v1",
                "issue": 110,
                "automatedValidation": "failed",
                "releaseDisposition": "pending-owner",
                "phase1Unlocked": False,
                "blockingChecks": ["promotionInputValidation"],
                "fallback": "do-not-publish-or-unlock-phase-1",
                "failure": {"type": type(exc).__name__, "message": str(exc)},
            },
        )
        raise SystemExit(1) from exc
    print(json.dumps(gate, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
