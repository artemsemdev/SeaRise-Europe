"""Finalize immutable pre-verification evidence for one controlled candidate."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from searise_pipeline.supply_chain import SupplyChainContractError
from searise_pipeline.supply_chain.production_evidence import (
    ProductionEvidenceSummary,
    finalize_production_evidence,
)


def _canonical_success(summary: ProductionEvidenceSummary) -> bytes:
    return (
        json.dumps(
            {
                "candidateId": summary.candidate_id,
                "cryptographicVerification": False,
                "evidenceRoot": str(summary.evidence_root),
                "evidenceSha256": summary.evidence_sha256,
                "productionClaim": False,
                "provenanceSha256": summary.provenance_sha256,
                "publicationClaim": False,
                "sbomCount": summary.sbom_count,
                "scientificApproval": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _emit_committed_success(summary: ProductionEvidenceSummary) -> None:
    """Best-effort unbuffered reporting cannot reverse a durable commit."""
    try:
        remaining = memoryview(_canonical_success(summary))
        descriptor = sys.stdout.fileno()
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("success reporting made no progress")
            remaining = remaining[written:]
    except (OSError, ValueError):
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Run alone and single-threaded on an isolated protected runner. RUNNER_TEMP "
            "(or TMPDIR) and the output parent must be absolute, symlink-free, "
            "runner-owned private directories."
        ),
    )
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--controlled-build-run-id", required=True)
    parser.add_argument("--manifest-bundle", type=Path, required=True)
    parser.add_argument("--provenance-bundle", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = finalize_production_evidence(
            args.candidate_root,
            repository_root=args.repository_root,
            controlled_build_run_id=args.controlled_build_run_id,
            manifest_bundle=args.manifest_bundle,
            provenance_bundle=args.provenance_bundle,
            output_root=args.output_root,
        )
    except SupplyChainContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _emit_committed_success(summary)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
