#!/usr/bin/env python3
"""Generate or validate the candidate build-plane input SBOM foundation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from searise_pipeline.supply_chain.build_plane_sbom import (
    publish_build_plane_sbom,
    validate_build_plane_sbom,
)
from searise_pipeline.supply_chain.contracts import SupplyChainContractError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "validate"):
        command = commands.add_parser(name)
        command.add_argument("--repository-root", type=Path, default=Path.cwd())
        command.add_argument(
            "--inventory",
            type=Path,
            default=Path("contracts/supply-chain/v1/dependency-inventory.json"),
        )
        if name == "generate":
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--sbom", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repository_root = args.repository_root.absolute()
    try:
        if args.command == "generate":
            document = publish_build_plane_sbom(
                args.output,
                args.inventory,
                repository_root=repository_root,
            )
            destination = args.output
        else:
            document = validate_build_plane_sbom(
                args.sbom,
                args.inventory,
                repository_root=repository_root,
            )
            destination = args.sbom
        print(
            f"{args.command}d {len(document['components'])} build-plane components: "
            f"{destination}"
        )
    except (OSError, json.JSONDecodeError, SupplyChainContractError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
