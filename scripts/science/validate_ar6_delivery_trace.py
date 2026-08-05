#!/usr/bin/env python3
"""Validate a real Chromium trace and emit bound issue #110 delivery evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from searise_pipeline.release import create_delivery_report, load_release_contract


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--release-contract", type=Path, required=True)
    parser.add_argument("--build-timing", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = create_delivery_report(
        args.candidate,
        args.trace,
        args.harness,
        args.build_timing,
        contract=load_release_contract(args.release_contract),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
