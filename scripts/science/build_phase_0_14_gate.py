#!/usr/bin/env python3
"""Rebuild the checked-in Phase 0.14 complete-with-no-go evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from searise_pipeline.regional_fixture.phase_0_14_gate import (
    build_phase_0_14_no_go,
    canonical_phase_0_14_no_go_bytes,
    verify_phase_0_14_bindings,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("src/pipeline/science/evidence/phase-0-14-final-no-go.json"),
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    document = build_phase_0_14_no_go(repo_root)
    verify_phase_0_14_bindings(document, repo_root)
    output = repo_root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_phase_0_14_no_go_bytes(document))


if __name__ == "__main__":
    main()
