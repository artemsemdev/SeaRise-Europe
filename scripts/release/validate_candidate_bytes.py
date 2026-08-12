#!/usr/bin/env python3
"""Validate exact bytes of one assembled Phase 1 pre-sign candidate."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from searise_pipeline.candidate_completeness import (
    CandidateContractError,
    validate_candidate_root,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = validate_candidate_root(args.candidate_root)
    except CandidateContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"validated {summary.candidate_id}: {summary.artifact_count} artifacts, "
        f"{summary.artifact_bytes} bytes; production and publication not claimed"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
