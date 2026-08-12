#!/usr/bin/env python3
"""Assemble one complete, immutable Phase 1 synthetic candidate fixture."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from searise_pipeline.candidate_completeness import (
    CandidateAssemblyError,
    assemble_candidate_fixture,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="absolute new path below an owner-controlled, symlink-free parent",
    )
    args = parser.parse_args(argv)
    try:
        summary = assemble_candidate_fixture(args.receipt, args.output)
    except CandidateAssemblyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"assembled {summary.candidate_id}: {summary.artifact_count} artifacts; "
        "production and publication not claimed"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
