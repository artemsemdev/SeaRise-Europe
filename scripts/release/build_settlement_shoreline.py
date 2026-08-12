#!/usr/bin/env python3
"""Rebuild or verify the exact settlement shoreline and QA evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from searise_pipeline.settlements.coastline import (
    CoastlineContractError,
    build_coastline,
    build_coastline_evidence,
    load_coastline_policy,
)


def _canonical_json_bytes(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--source-lock",
        type=Path,
        default=Path("src/pipeline/sources/source-lock.phase-1-settlement-coastline.json"),
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("src/pipeline/settlements/shoreline-distance-policy-v1.json"),
    )
    parser.add_argument("--coastline-archive", type=Path, required=True)
    parser.add_argument("--minor-islands-archive", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    source_lock = repo_root / args.source_lock
    policy_path = repo_root / args.policy
    policy = load_coastline_policy(policy_path)
    try:
        content = build_coastline(
            source_lock,
            policy_path,
            {
                "coastline": args.coastline_archive,
                "minor-islands-coastline": args.minor_islands_archive,
            },
        )
        output = policy["output"]
        if (len(content), hashlib.sha256(content).hexdigest()) != (
            output["byteSize"],
            output["sha256"],
        ):
            raise CoastlineContractError("rebuilt shoreline differs from declared output identity")
        output_path = repo_root / output["path"]
        if args.write:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(content)
        elif output_path.read_bytes() != content:
            raise CoastlineContractError("checked-in shoreline differs from exact rebuild")

        evidence = _canonical_json_bytes(build_coastline_evidence(repo_root, policy_path))
        evidence_path = repo_root / policy["evidencePath"]
        if args.write:
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_bytes(evidence)
        elif evidence_path.read_bytes() != evidence:
            raise CoastlineContractError("checked-in shoreline QA evidence is stale")
    except (CoastlineContractError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
