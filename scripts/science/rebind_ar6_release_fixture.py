#!/usr/bin/env python3
"""Rebind the committed offline AR6 fixture after one pinned contract edit."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from searise_pipeline.release import (
    load_release_contract,
    load_source_fixture,
    rebind_source_fixture_contract,
)
from searise_pipeline.science.contracts import ScienceContractError

REPOSITORY_ROOT = Path(__file__).parents[2]
CONTRACT_PATH = REPOSITORY_ROOT / "src/pipeline/science/ar6-regional-release.json"
FIXTURE_ROOT = REPOSITORY_ROOT / "src/pipeline/fixtures/ar6-regional-release"
FIXTURE_PATH = FIXTURE_ROOT / "source-fixture.json.gz"
RECEIPT_PATH = FIXTURE_ROOT / "source-fixture-receipt.json"
AUTHORIZED_PREVIOUS_CONTRACT_SHA256 = (
    "be5f9a1b43a97819a0a06a4cfdeb388896205e8361d7aa3f70158ac3d7eec93f"
)
AUTHORIZED_PREVIOUS_FIXTURE_SHA256 = (
    "edd929a5ce15447d6a960cbc94ec716e2d22f44613dce1e009a6855463c4544c"
)
AUTHORIZED_PREVIOUS_RECEIPT_SHA256 = (
    "06e670a641bf339f984ec7a7b798c2ee8873987fa147762457b46f58b2feb78c"
)
AUTHORIZED_REBOUND_FIXTURE_SHA256 = (
    "dcf79b058fb73fee9a78768ed813f7239998446281db9f7cb5e4afa0252d5484"
)
AUTHORIZED_REBOUND_RECEIPT_SHA256 = (
    "aa592ab0f1dc222ee390bbf35c03e86d5124baed72544d52d8801355ab0cde6a"
)
AUTHORIZED_PREVIOUS_RECEIPT: Mapping[str, Any] = {
    "archiveSha256": "d3b1c2ed093cca491db2461e67b782bcca98763d326378ffee39908c2b094e91",
    "byteSize": 119705,
    "derivation": "verified-archive-native-grid-subset-no-resampling",
    "fixtureId": "ar6-europe-regional-source-v1",
    "memberSha256": {
        "ssp1-26": "28ca163c13470047aefb75ae8f4a8bc6e06c3e44b824ff37e8743ca8d3a1b716",
        "ssp2-45": "3f31aadb53b7962a729a839cd58e841f171e72575f9e2b802399be6656aa8cb8",
        "ssp5-85": "b3bcf98c6a17b43fbb24d0e60ede382886f3487883022aa88b513ea582a607e0",
    },
    "releaseContractSha256": AUTHORIZED_PREVIOUS_CONTRACT_SHA256,
    "scientificReleaseEligible": False,
    "sha256": AUTHORIZED_PREVIOUS_FIXTURE_SHA256,
    "sourceArchiveVerifiedForThisWrite": True,
}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _receipt_bytes(receipt: Mapping[str, Any]) -> bytes:
    return (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _deterministic_gzip(document: Mapping[str, Any]) -> bytes:
    payload = (
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as stream:
        stream.write(payload)
    return output.getvalue()


def _authorized_previous_fixture(rebound: bytes) -> bytes:
    document = json.loads(gzip.decompress(rebound))
    document["releaseContractSha256"] = AUTHORIZED_PREVIOUS_CONTRACT_SHA256
    previous = _deterministic_gzip(document)
    if _sha256(previous) != AUTHORIZED_PREVIOUS_FIXTURE_SHA256:
        raise ScienceContractError(
            "Rebound fixture cannot reconstruct authorized previous bytes"
        )
    return previous


def _replace(path: Path, payload: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(payload)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def migrate_fixture_pair(
    fixture_path: Path,
    receipt_path: Path,
    contract: Mapping[str, Any],
) -> None:
    """Migrate or recover only the two independently pinned pair states."""
    fixture_bytes = fixture_path.read_bytes()
    receipt_bytes = receipt_path.read_bytes()
    fixture_sha256 = _sha256(fixture_bytes)
    receipt_sha256 = _sha256(receipt_bytes)
    receipt = json.loads(receipt_bytes)

    if (
        fixture_sha256 == AUTHORIZED_REBOUND_FIXTURE_SHA256
        and receipt_sha256 == AUTHORIZED_REBOUND_RECEIPT_SHA256
    ):
        load_source_fixture(fixture_path, receipt=receipt, release_contract=contract)
        return
    if receipt_sha256 != AUTHORIZED_PREVIOUS_RECEIPT_SHA256:
        raise ScienceContractError("Fixture pair is not an authorized migration state")
    if receipt != AUTHORIZED_PREVIOUS_RECEIPT:
        raise ScienceContractError("Authorized previous receipt bytes changed meaning")

    with tempfile.TemporaryDirectory(dir=fixture_path.parent) as directory:
        previous_path = Path(directory) / "source-fixture.json.gz"
        if fixture_sha256 == AUTHORIZED_PREVIOUS_FIXTURE_SHA256:
            previous_path.write_bytes(fixture_bytes)
        elif fixture_sha256 == AUTHORIZED_REBOUND_FIXTURE_SHA256:
            previous_path.write_bytes(_authorized_previous_fixture(fixture_bytes))
        else:
            raise ScienceContractError(
                "Fixture pair is not an authorized migration state"
            )
        rebound_fixture, rebound_receipt = rebind_source_fixture_contract(
            previous_path,
            receipt=AUTHORIZED_PREVIOUS_RECEIPT,
            release_contract=contract,
            expected_previous_contract_sha256=AUTHORIZED_PREVIOUS_CONTRACT_SHA256,
            expected_previous_fixture_sha256=AUTHORIZED_PREVIOUS_FIXTURE_SHA256,
            observed_previous_receipt_sha256=receipt_sha256,
            expected_previous_receipt_sha256=AUTHORIZED_PREVIOUS_RECEIPT_SHA256,
        )
    rebound_receipt_bytes = _receipt_bytes(rebound_receipt)
    if (
        _sha256(rebound_fixture) != AUTHORIZED_REBOUND_FIXTURE_SHA256
        or _sha256(rebound_receipt_bytes) != AUTHORIZED_REBOUND_RECEIPT_SHA256
    ):
        raise ScienceContractError(
            "Rebound fixture pair differs from reviewed target bytes"
        )

    if fixture_sha256 != AUTHORIZED_REBOUND_FIXTURE_SHA256:
        _replace(fixture_path, rebound_fixture)
    _replace(receipt_path, rebound_receipt_bytes)
    load_source_fixture(
        fixture_path, receipt=rebound_receipt, release_contract=contract
    )


def main() -> None:
    migrate_fixture_pair(
        FIXTURE_PATH, RECEIPT_PATH, load_release_contract(CONTRACT_PATH)
    )


if __name__ == "__main__":
    main()
