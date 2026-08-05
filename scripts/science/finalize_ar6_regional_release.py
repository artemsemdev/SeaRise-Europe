#!/usr/bin/env python3
"""Finalize issue #110 only from evidence bound to an immutable candidate."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from searise_pipeline.release import finalize_recovery_gate, load_release_contract


def _load(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--release-contract", type=Path, required=True)
    parser.add_argument("--reproducibility-report", type=Path, required=True)
    parser.add_argument("--delivery-report", type=Path, required=True)
    parser.add_argument("--owner-evidence", type=Path, required=True)
    parser.add_argument("--integration-evidence", type=Path, required=True)
    parser.add_argument("--promotion-record", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    args = parser.parse_args()
    gate = finalize_recovery_gate(
        args.candidate,
        contract=load_release_contract(args.release_contract),
        reproducibility_report=_load(args.reproducibility_report),
        delivery_report=_load(args.delivery_report),
        owner_evidence=_load(args.owner_evidence),
        integration_evidence=_load(args.integration_evidence),
        promotion_record=_load(args.promotion_record),
        owner_evidence_path=args.owner_evidence,
        integration_evidence_path=args.integration_evidence,
        repository_root=args.repository_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(gate, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
