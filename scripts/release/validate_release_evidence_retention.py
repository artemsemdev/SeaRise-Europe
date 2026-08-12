#!/usr/bin/env python3
"""Validate one exact local release evidence handoff without external policy claims."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    validate_release_evidence_retention,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retention-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_release_evidence_retention(args.retention_root)
    except (OSError, SupplyChainContractError) as exc:
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
