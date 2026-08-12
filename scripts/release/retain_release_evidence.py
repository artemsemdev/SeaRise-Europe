#!/usr/bin/env python3
"""Build one immutable release-lifetime supply-chain evidence handoff."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    retain_release_evidence,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--cryptographic-receipt", type=Path, required=True)
    parser.add_argument("--public-readback-receipt", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = retain_release_evidence(
            args.candidate_root,
            args.evidence_root,
            args.cryptographic_receipt,
            args.public_readback_receipt,
            args.output_root,
            repository_root=args.repository_root,
        )
    except SupplyChainContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "candidateId": result.candidate_id,
                "dataReleaseId": result.data_release_id,
                "deterministicIdentity": result.deterministic_identity,
                "retainedFileCount": result.retained_file_count,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
