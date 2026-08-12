"""Reverify Sigstore subjects and compare exact public manifest/provenance bytes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    verify_public_signed_subjects,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--controlled-build-run-id", required=True)
    parser.add_argument("--cosign-executable", type=Path, required=True)
    parser.add_argument("--cosign-tool-lock", type=Path, required=True)
    parser.add_argument("--trusted-cosign-tool-lock-sha256", required=True)
    parser.add_argument("--expected-origin", required=True)
    parser.add_argument("--manifest-url", required=True)
    parser.add_argument("--provenance-url", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify_public_signed_subjects(
            args.candidate_root,
            args.evidence_root,
            repository_root=args.repository_root,
            controlled_build_run_id=args.controlled_build_run_id,
            cosign_executable=args.cosign_executable,
            cosign_tool_lock=args.cosign_tool_lock,
            trusted_cosign_tool_lock_sha256=args.trusted_cosign_tool_lock_sha256,
            expected_origin=args.expected_origin,
            manifest_url=args.manifest_url,
            provenance_url=args.provenance_url,
            receipt_path=args.receipt,
        )
    except (OSError, SupplyChainContractError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"verified {len(result.receipt['subjects'])} public signed subjects; "
        "production, publication approval, and scientific approval not claimed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
