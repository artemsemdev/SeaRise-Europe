"""Tests for the immutable Cosign Linux AMD64 source lock."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from searise_pipeline.supply_chain import SupplyChainContractError, validate_cosign_tool_lock

ROOT = Path(__file__).resolve().parents[4]
LOCK = ROOT / "contracts/supply-chain/v1/tools/cosign-linux-amd64.json"
LOCK_SHA256 = "dbc14b1ecc49d3fbbfb907504e50c2c18d398e1c5aa55df1f1002d709c7b70e9"
RELEASE_ROOT = "https://github.com/sigstore/cosign/releases"


def _canonical(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    executable = tmp_path / "cosign-linux-amd64"
    executable.write_bytes(b"reviewed test executable")
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    checksums = tmp_path / "cosign_checksums.txt"
    checksums.write_text(f"{executable_sha256}  cosign-linux-amd64\n", encoding="utf-8")
    lock = {
        "$schema": "https://artemsemdev.github.io/SeaRise-Europe/contracts/supply-chain/v1/cosign-tool-lock.schema.json",
        "schemaVersion": "1.0.0",
        "contractId": "phase-1-cosign-linux-amd64-v1",
        "tool": "cosign",
        "version": "3.0.6",
        "platform": "linux-amd64",
        "releaseUrl": f"{RELEASE_ROOT}/tag/v3.0.6",
        "executable": {
            "name": "cosign-linux-amd64",
            "url": f"{RELEASE_ROOT}/download/v3.0.6/cosign-linux-amd64",
            "sha256": executable_sha256,
            "byteSize": executable.stat().st_size,
        },
        "checksumEvidence": {
            "name": "cosign_checksums.txt",
            "url": f"{RELEASE_ROOT}/download/v3.0.6/cosign_checksums.txt",
            "sha256": hashlib.sha256(checksums.read_bytes()).hexdigest(),
            "byteSize": checksums.stat().st_size,
            "entry": f"{executable_sha256}  cosign-linux-amd64",
        },
    }
    lock_path = tmp_path / "cosign-tool-lock.json"
    lock_path.write_bytes(_canonical(lock))
    return lock_path, executable, checksums


def test_checked_in_lock_binds_reviewed_official_release_assets() -> None:
    summary = validate_cosign_tool_lock(LOCK, trusted_lock_sha256=LOCK_SHA256)

    assert hashlib.sha256(LOCK.read_bytes()).hexdigest() == LOCK_SHA256
    assert (summary.version, summary.platform) == ("3.0.6", "linux-amd64")
    assert summary.executable_sha256 == (
        "c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74"
    )
    assert summary.executable_byte_size == 135178161


def test_exact_lock_executable_and_checksum_bytes_validate_together(tmp_path: Path) -> None:
    lock, executable, checksums = _fixture(tmp_path)
    summary = validate_cosign_tool_lock(
        lock,
        trusted_lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
        executable_path=executable,
        checksum_path=checksums,
    )

    assert summary.executable_sha256 == hashlib.sha256(executable.read_bytes()).hexdigest()


@pytest.mark.parametrize("target", ["lock", "executable", "checksums"])
def test_changed_trusted_bytes_fail_closed(tmp_path: Path, target: str) -> None:
    lock, executable, checksums = _fixture(tmp_path)
    trusted = hashlib.sha256(lock.read_bytes()).hexdigest()
    {"lock": lock, "executable": executable, "checksums": checksums}[target].write_bytes(b"changed")

    with pytest.raises(SupplyChainContractError):
        validate_cosign_tool_lock(
            lock,
            trusted_lock_sha256=trusted,
            executable_path=executable,
            checksum_path=checksums,
        )


def test_assets_cannot_be_partially_validated_or_reached_through_symlink(tmp_path: Path) -> None:
    lock, executable, checksums = _fixture(tmp_path)
    trusted = hashlib.sha256(lock.read_bytes()).hexdigest()
    with pytest.raises(SupplyChainContractError, match="validated together"):
        validate_cosign_tool_lock(
            lock,
            trusted_lock_sha256=trusted,
            executable_path=executable,
        )

    link = tmp_path / "linked-checksums.txt"
    link.symlink_to(checksums)
    with pytest.raises(SupplyChainContractError, match="without symlinks"):
        validate_cosign_tool_lock(
            lock,
            trusted_lock_sha256=trusted,
            executable_path=executable,
            checksum_path=link,
        )
