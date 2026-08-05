#!/usr/bin/env python3
"""Compare two issue #110 builds and write reproducibility evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from searise_pipeline.release import compare_release_candidates, load_release_contract


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--first-environment", required=True)
    parser.add_argument("--second-environment", required=True)
    parser.add_argument("--release-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = compare_release_candidates(
        args.first,
        args.second,
        first_environment=args.first_environment,
        second_environment=args.second_environment,
        contract=load_release_contract(args.release_contract),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
