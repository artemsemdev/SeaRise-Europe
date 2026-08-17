#!/usr/bin/env python3
"""Rebind the committed offline AR6 fixture after a non-scientific contract edit."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from searise_pipeline.release import (
    load_release_contract,
    load_source_fixture,
    rebind_source_fixture_contract,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
CONTRACT_PATH = REPOSITORY_ROOT / "src/pipeline/science/ar6-regional-release.json"
FIXTURE_ROOT = REPOSITORY_ROOT / "src/pipeline/fixtures/ar6-regional-release"
FIXTURE_PATH = FIXTURE_ROOT / "source-fixture.json.gz"
RECEIPT_PATH = FIXTURE_ROOT / "source-fixture-receipt.json"
AUTHORIZED_PREVIOUS_CONTRACT_SHA256 = (
    "be5f9a1b43a97819a0a06a4cfdeb388896205e8361d7aa3f70158ac3d7eec93f"
)


def _replace(path: Path, payload: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(payload)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def main() -> None:
    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    contract = load_release_contract(CONTRACT_PATH)
    if receipt.get("releaseContractSha256") != AUTHORIZED_PREVIOUS_CONTRACT_SHA256:
        load_source_fixture(FIXTURE_PATH, receipt=receipt, release_contract=contract)
        return
    fixture, rebound_receipt = rebind_source_fixture_contract(
        FIXTURE_PATH,
        receipt=receipt,
        release_contract=contract,
        expected_previous_contract_sha256=AUTHORIZED_PREVIOUS_CONTRACT_SHA256,
    )
    _replace(FIXTURE_PATH, fixture)
    _replace(
        RECEIPT_PATH,
        (json.dumps(rebound_receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


if __name__ == "__main__":
    main()
