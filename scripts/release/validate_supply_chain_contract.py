"""Validate versioned supply-chain evidence without making a signing claim."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    load_json,
    parse_timestamp,
    validate_dependency_exception,
    validate_dependency_inventory,
    validate_evidence_files,
)


def _sbom(value: str) -> tuple[str, Path]:
    logical_path, separator, file_path = value.partition("=")
    if not separator or not logical_path or not file_path:
        raise argparse.ArgumentTypeError("SBOM must use LOGICAL_PATH=FILE")
    return logical_path, Path(file_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    evidence = commands.add_parser("evidence")
    evidence.add_argument("--envelope", type=Path, required=True)
    evidence.add_argument("--identity-policy", type=Path, required=True)
    evidence.add_argument("--sbom", type=_sbom, action="append", required=True)
    exception = commands.add_parser("exception")
    exception.add_argument("--document", type=Path, required=True)
    exception.add_argument("--as-of", required=True)
    inventory = commands.add_parser("inventory")
    inventory.add_argument("--document", type=Path, required=True)
    inventory.add_argument("--repository-root", type=Path, default=Path.cwd())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "evidence":
            sboms = dict(args.sbom)
            if len(sboms) != len(args.sbom):
                raise SupplyChainContractError("duplicate SBOM logical path")
            envelope = validate_evidence_files(
                args.envelope,
                args.identity_policy,
                sboms,
            )
            print(f"validated synthetic evidence envelope: {envelope['candidateId']}")
        elif args.command == "exception":
            document = load_json(args.document)
            validate_dependency_exception(document, as_of=parse_timestamp(args.as_of))
            print(f"validated dependency exception: {document['exceptionId']}")
        else:
            document = validate_dependency_inventory(
                args.document,
                repository_root=args.repository_root.resolve(),
            )
            input_count = sum(
                len(component["inputs"]) for component in document["components"]
            )
            print(f"validated {input_count} dependency-defining inputs")
    except (OSError, json.JSONDecodeError, SupplyChainContractError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
