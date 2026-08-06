#!/usr/bin/env python3
"""Promote Phase 0R only inside its protected GitHub owner workflow."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from searise_pipeline.release.owner_promotion import (
    GitHubApi,
    context_from_environment,
    promote_phase_0r_release,
)
from searise_pipeline.science import ScienceContractError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation-run-id", required=True)
    parser.add_argument("--evidence-pr-number", required=True)
    parser.add_argument("--decision", choices=("approved", "rejected"), required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    workspace_value = os.environ.get("GITHUB_WORKSPACE", "")
    runner_temp_value = os.environ.get("RUNNER_TEMP", "")
    if not workspace_value or not runner_temp_value:
        raise SystemExit("GITHUB_WORKSPACE and RUNNER_TEMP are required")
    workspace = Path(workspace_value)
    runner_temp = Path(runner_temp_value)
    try:
        gate = promote_phase_0r_release(
            args.validation_run_id,
            args.evidence_pr_number,
            args.decision,
            repository_root=workspace,
            output_root=runner_temp / "phase-0r-owner-promotion",
            download_root=runner_temp / "phase-0r-owner-promotion-download",
            context=context_from_environment(),
            api=GitHubApi(os.environ.get("GITHUB_TOKEN", "")),
        )
    except (OSError, KeyError, ValueError, ScienceContractError) as exc:
        raise SystemExit(f"Phase 0R owner promotion failed closed: {exc}") from exc
    print(json.dumps(gate, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
