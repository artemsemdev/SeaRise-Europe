#!/usr/bin/env python3
"""Rebuild the dependency-independent Phase 0.13 review preflight."""

from __future__ import annotations

import argparse
from pathlib import Path

from searise_pipeline.science import (
    build_pending_scope_connectivity_review,
    canonical_json_bytes,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("src/pipeline/science/scope-connectivity-review.json"),
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else repo_root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        canonical_json_bytes(build_pending_scope_connectivity_review(repo_root))
    )


if __name__ == "__main__":
    main()
