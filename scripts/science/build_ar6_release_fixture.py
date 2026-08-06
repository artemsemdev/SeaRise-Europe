#!/usr/bin/env python3
"""Derive the small checked-in AR6 regional source fixture from verified bytes."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from searise_pipeline.release import (
    build_source_from_verified_archive,
    load_release_contract,
    write_source_fixture,
)


def _load(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    path.write_text(encoded, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--source-semantics", type=Path, required=True)
    parser.add_argument("--release-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    contract = load_release_contract(args.release_contract)
    source = build_source_from_verified_archive(
        args.archive,
        source_lock=_load(args.source_lock),
        source_semantics=_load(args.source_semantics),
        release_contract=contract,
        release_contract_path=args.release_contract,
    )
    receipt = write_source_fixture(source, args.output)
    _write_json(args.receipt, receipt)


if __name__ == "__main__":
    main()
