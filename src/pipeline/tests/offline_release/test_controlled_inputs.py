"""Security and workflow contracts for controlled regional/full builds."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).parents[4]
SCRIPT = REPO_ROOT / "scripts/release/prepare_controlled_offline_inputs.py"
REGIONAL_PREFIX = "build-inputs/offline-release/regional"


def _load_script() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "prepare_controlled_offline_inputs",
        SCRIPT,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


CONTROLLED_INPUTS = _load_script()
InputBundleError = CONTROLLED_INPUTS.InputBundleError
prepare_inputs = CONTROLLED_INPUTS.prepare_inputs


def _regular(name: str, payload: bytes = b"{}\n") -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = 0o644
    return member, payload


def _special(name: str, member_type: bytes) -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.type = member_type
    member.linkname = "manifest.json"
    return member, b""


def _write_tar(
    path: Path,
    entries: list[tuple[tarfile.TarInfo, bytes]],
    *,
    mode: str = "w:",
) -> str:
    with tarfile.open(path, mode=mode) as package:
        for member, payload in entries:
            package.addfile(member, io.BytesIO(payload) if member.isreg() else None)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _required_entries() -> list[tuple[tarfile.TarInfo, bytes]]:
    return [
        _regular(f"{REGIONAL_PREFIX}/manifest.json"),
        _regular(f"{REGIONAL_PREFIX}/receipts/sources.json"),
    ]


def test_reviewed_plain_tar_is_verified_and_atomically_prepared(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "offline-inputs.tar"
    checksum = _write_tar(
        archive,
        [
            *_required_entries(),
            _regular(f"{REGIONAL_PREFIX}/analysis/example.tif", b"scientific-bytes"),
        ],
    )
    destination = tmp_path / "prepared"

    result = prepare_inputs(
        archive,
        destination,
        profile="regional",
        expected_sha256=checksum,
    )

    assert result.archive_sha256 == checksum
    assert result.file_count == 3
    assert result.total_bytes == len(b"{}\n") * 2 + len(b"scientific-bytes")
    assert (destination / REGIONAL_PREFIX / "manifest.json").is_file()
    assert not list(tmp_path.glob(".offline-inputs-*"))


def test_bundle_identity_mismatch_fails_before_destination_creation(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "offline-inputs.tar"
    _write_tar(archive, _required_entries())
    destination = tmp_path / "prepared"

    with pytest.raises(InputBundleError, match="reviewed identity"):
        prepare_inputs(
            archive,
            destination,
            profile="regional",
            expected_sha256="0" * 64,
        )

    assert not destination.exists()


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../escape.json",
        "/absolute.json",
        f"{REGIONAL_PREFIX}/../other/escape.json",
        "build-inputs/offline-release/full-europe/manifest.json",
        f"{REGIONAL_PREFIX}\\escape.json",
    ],
)
def test_unsafe_or_cross_profile_paths_are_rejected_atomically(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    archive = tmp_path / "offline-inputs.tar"
    checksum = _write_tar(archive, [*_required_entries(), _regular(unsafe_name)])
    destination = tmp_path / "prepared"

    with pytest.raises(InputBundleError):
        prepare_inputs(
            archive,
            destination,
            profile="regional",
            expected_sha256=checksum,
        )

    assert not destination.exists()
    assert not (tmp_path / "escape.json").exists()


@pytest.mark.parametrize(
    "member_type",
    [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE],
)
def test_links_and_special_members_are_rejected(
    tmp_path: Path,
    member_type: bytes,
) -> None:
    archive = tmp_path / "offline-inputs.tar"
    checksum = _write_tar(
        archive,
        [*_required_entries(), _special(f"{REGIONAL_PREFIX}/unsafe", member_type)],
    )

    with pytest.raises(InputBundleError, match="only directories and regular files"):
        prepare_inputs(
            archive,
            tmp_path / "prepared",
            profile="regional",
            expected_sha256=checksum,
        )


def test_duplicate_or_incomplete_bundles_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.tar"
    checksum = _write_tar(
        duplicate,
        [*_required_entries(), _regular(f"{REGIONAL_PREFIX}/manifest.json")],
    )
    with pytest.raises(InputBundleError, match="duplicate"):
        prepare_inputs(
            duplicate,
            tmp_path / "duplicate-output",
            profile="regional",
            expected_sha256=checksum,
        )

    incomplete = tmp_path / "incomplete.tar"
    checksum = _write_tar(
        incomplete,
        [_regular(f"{REGIONAL_PREFIX}/manifest.json")],
    )
    with pytest.raises(InputBundleError, match="missing"):
        prepare_inputs(
            incomplete,
            tmp_path / "incomplete-output",
            profile="regional",
            expected_sha256=checksum,
        )


def test_compressed_archives_are_not_accepted_as_the_plain_tar_contract(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "offline-inputs.tar.gz"
    checksum = _write_tar(archive, _required_entries(), mode="w:gz")

    with pytest.raises(InputBundleError, match="uncompressed POSIX tar"):
        prepare_inputs(
            archive,
            tmp_path / "prepared",
            profile="regional",
            expected_sha256=checksum,
        )
