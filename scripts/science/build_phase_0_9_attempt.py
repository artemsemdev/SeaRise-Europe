#!/usr/bin/env python3
"""Rebuild the checked-in Phase 0.9 blocked-attempt evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from searise_pipeline.regional_fixture.phase_0_9_attempt import (
    build_blocked_phase_0_9_attempt,
    canonical_phase_0_9_attempt_bytes,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("src/pipeline/science/evidence/phase-0-9-regional-attempt.json"),
    )
    args = parser.parse_args()
    document = build_blocked_phase_0_9_attempt(args.repo_root.resolve())
    output = args.repo_root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_phase_0_9_attempt_bytes(document))


if __name__ == "__main__":
    main()
