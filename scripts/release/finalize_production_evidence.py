"""Finalize immutable pre-verification evidence for one controlled candidate."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from searise_pipeline.supply_chain import SupplyChainContractError
from searise_pipeline.supply_chain.production_evidence import (
    finalize_production_evidence,
)


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
    print(
        f"finalized {summary.candidate_id}: {summary.sbom_count} SBOMs; "
        "cryptographic verification, production, publication, and scientific approval not claimed"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
