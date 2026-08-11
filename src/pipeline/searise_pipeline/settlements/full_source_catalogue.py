"""Immutable source contract for full GeoNames catalog staging.

This module fully verifies decompressed members but neither stages nor publishes data.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .alternate_names import NORMALIZATION_POLICY_VERSION, load_normalization_policy
from .catalogue import CATALOGUE_POLICY_VERSION, load_catalogue_policy
from .geonames import RAW_ANOMALY_POLICY_VERSION

ISO_LANGUAGE_HEADER = b"ISO 639-3\tISO 639-2\tISO 639-1\tLanguage Name"
SOURCE_LOCK_SHA256 = "3e6d58578f9a9f387804f9cfbc5cada3a39a5d1460a67ac00285e2236f9e2eee"
CATALOGUE_POLICY_SHA256 = "cd850f85c6eac4627c8995f3d4497456a5d7975d1d3cf308604c604608fd3e8f"
NORMALIZATION_POLICY_SHA256 = "257856a1f0f0168569bdd609c9e60813cf59fd6fb3d3eacbb970309fb1cd1cb5"
MINIMUM_FREE_BYTES = 20 * 1024**3

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CRC32 = re.compile(r"^[0-9a-f]{8}$")
_MEMBER_PATH = re.compile(r"^[A-Za-z0-9._-]+$")


class FullSourceContractError(ValueError):
    """A full-source input or its immutable identity is invalid."""


@dataclass(frozen=True)
class LockedMember:
    path: str
    sha256: str
    byte_size: int
    compressed_byte_size: int
    crc32: str
    row_count: int
    header: bytes | None = None

    def __post_init__(self) -> None:
        if (
            not _MEMBER_PATH.fullmatch(self.path)
            or not _SHA256.fullmatch(self.sha256)
            or not _CRC32.fullmatch(self.crc32)
            or self.byte_size < 1
            or self.compressed_byte_size < 1
            or self.row_count < 1
            or (
                self.header is not None
                and (
                    not isinstance(self.header, bytes)
                    or not self.header
                    or b"\n" in self.header
                    or b"\r" in self.header
                )
            )
        ):
            raise FullSourceContractError("locked ZIP member identity is invalid")


@dataclass(frozen=True)
class LockedAsset:
    sha256: str
    byte_size: int
    members: tuple[LockedMember, ...] = ()
    row_count: int = 0

    def __post_init__(self) -> None:
        paths = tuple(item.path for item in self.members)
        if (
            not _SHA256.fullmatch(self.sha256)
            or self.byte_size < 1
            or self.row_count < 0
            or not isinstance(self.members, tuple)
            or len(paths) != len(set(paths))
            or (self.members and self.row_count)
        ):
            raise FullSourceContractError("locked asset identity is invalid")


@dataclass(frozen=True)
class FullSourceStageContract:
    source_lock_sha256: str
    catalogue_policy_sha256: str
    normalization_policy_sha256: str
    all_countries: LockedAsset
    alternate_names: LockedAsset
    admin1: LockedAsset
    readme: LockedAsset
    minimum_free_bytes: int = MINIMUM_FREE_BYTES

    def __post_init__(self) -> None:
        if (
            any(
                not _SHA256.fullmatch(value)
                for value in (
                    self.source_lock_sha256,
                    self.catalogue_policy_sha256,
                    self.normalization_policy_sha256,
                )
            )
            or self.minimum_free_bytes < 0
            or len(self.all_countries.members) != 1
            or self.all_countries.members[0].path != "allCountries.txt"
            or self.all_countries.members[0].header is not None
            or tuple(item.path for item in self.alternate_names.members)
            != ("alternateNamesV2.txt", "iso-languagecodes.txt")
            or self.alternate_names.members[0].header is not None
            or self.alternate_names.members[1].header != ISO_LANGUAGE_HEADER
            or self.admin1.members
            or self.admin1.row_count < 1
            or self.readme.members
            or self.readme.row_count
        ):
            raise FullSourceContractError("full-source stage contract is malformed")


@dataclass(frozen=True)
class FullSourceStageInputs:
    all_countries_zip: Path
    alternate_names_zip: Path
    admin1: Path
    readme: Path
    source_lock: Path
    catalogue_policy: Path
    normalization_policy: Path


PRODUCTION_CONTRACT = FullSourceStageContract(
    SOURCE_LOCK_SHA256,
    CATALOGUE_POLICY_SHA256,
    NORMALIZATION_POLICY_SHA256,
    LockedAsset(
        "06f423eaf760d28101cd11a9744ade90f65c618d073ac2168501c388e1bd4afa",
        419923777,
        (
            LockedMember(
                "allCountries.txt",
                "4217bcadfce0d86d7f39244259dbbb96e5d1a610faedc3b4761bb96dcc492bf8",
                1782635669,
                419923631,
                "27133946",
                13455006,
            ),
        ),
    ),
    LockedAsset(
        "eaea640b50b7081f7270d9563720b66d6b345af81522a6eb8ee55873507b17fe",
        202510374,
        (
            LockedMember(
                "alternateNamesV2.txt",
                "63453d348543a363bbd33a461c41e769de59d293c3fd62ca408eb3e2b0b47612",
                777625687,
                202448178,
                "e311a5a6",
                19037112,
            ),
            LockedMember(
                "iso-languagecodes.txt",
                "cb0d34f492775deec8ec5713da6efa4463dad99b5e7ba2172bd094cfdcb76571",
                137908,
                61908,
                "4e1f14da",
                7929,
                ISO_LANGUAGE_HEADER,
            ),
        ),
    ),
    LockedAsset(
        "34784457b76b988a669dff7c3e4b104e4902c0875643cff019281ac79dfa2992",
        151572,
        row_count=3865,
    ),
    LockedAsset(
        "b1957379b6c1242c700c98ac9a8aa0a09f56c3c0a50ee72175527005f48ef2c5",
        8843,
    ),
)


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _require_regular(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise FullSourceContractError(f"cannot inspect {label}: {exc}") from exc
    if path.is_symlink() or not stat.S_ISREG(mode):
        raise FullSourceContractError(f"{label} must be a regular non-symlink file")


def _verify_file(path: Path, locked: LockedAsset, label: str) -> None:
    _require_regular(path, label)
    if _sha256(path) != (locked.sha256, locked.byte_size):
        raise FullSourceContractError(f"{label} bytes differ from the locked identity")


def _verify_archive(path: Path, locked: LockedAsset, label: str) -> None:
    _verify_file(path, locked, label)
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if tuple(item.filename for item in entries) != tuple(
                item.path for item in locked.members
            ):
                raise FullSourceContractError(
                    f"{label} member inventory differs from the locked identity"
                )
            for member, info in zip(locked.members, entries):
                if (info.file_size, info.compress_size, f"{info.CRC:08x}") != (
                    member.byte_size,
                    member.compressed_byte_size,
                    member.crc32,
                ):
                    raise FullSourceContractError(
                        f"{member.path} ZIP metadata differs from the locked identity"
                    )
                digest = hashlib.sha256()
                size = rows = 0
                with archive.open(info) as stream:
                    if member.header is not None:
                        header = stream.readline()
                        digest.update(header)
                        size += len(header)
                        if header.rstrip(b"\r\n") != member.header:
                            raise FullSourceContractError(
                                f"{member.path} header differs from the locked identity"
                            )
                    for raw in stream:
                        digest.update(raw)
                        size += len(raw)
                        rows += 1
                if (digest.hexdigest(), size, rows) != (
                    member.sha256,
                    member.byte_size,
                    member.row_count,
                ):
                    raise FullSourceContractError(
                        f"{member.path} content or row count differs from the locked identity"
                    )
    except zipfile.BadZipFile as exc:
        raise FullSourceContractError(f"{label} is not a valid ZIP archive") from exc
    _verify_file(path, locked, label)


def _verify_plain_rows(path: Path, locked: LockedAsset, label: str) -> None:
    _verify_file(path, locked, label)
    with path.open("rb") as stream:
        rows = sum(1 for _ in stream)
    if rows != locked.row_count:
        raise FullSourceContractError(f"{label} row count differs from the locked identity")
    _verify_file(path, locked, label)


def full_source_bindings(
    contract: FullSourceStageContract = PRODUCTION_CONTRACT,
) -> dict[str, Any]:
    """Return deterministic policy, asset, member, and row-count bindings."""

    def asset(value: LockedAsset) -> dict[str, Any]:
        return {
            "sha256": value.sha256,
            "byteSize": value.byte_size,
            "rowCount": value.row_count,
            "members": [
                {
                    "path": item.path,
                    "sha256": item.sha256,
                    "byteSize": item.byte_size,
                    "compressedByteSize": item.compressed_byte_size,
                    "crc32": item.crc32,
                    "rowCount": item.row_count,
                }
                for item in value.members
            ],
        }

    return {
        "bindingVersion": "full-source-catalogue-inputs-v1",
        "claimBoundary": {
            "decompressedMembersVerified": True,
            "stagingPerformed": False,
            "publicationClaim": False,
        },
        "minimumFreeBytes": contract.minimum_free_bytes,
        "sourceLockSha256": contract.source_lock_sha256,
        "policies": {
            "catalogue": {
                "version": CATALOGUE_POLICY_VERSION,
                "sha256": contract.catalogue_policy_sha256,
            },
            "names": {
                "version": NORMALIZATION_POLICY_VERSION,
                "sha256": contract.normalization_policy_sha256,
            },
            "rawSource": {"version": RAW_ANOMALY_POLICY_VERSION},
        },
        "assets": {
            "allCountries": asset(contract.all_countries),
            "alternateNames": asset(contract.alternate_names),
            "admin1": asset(contract.admin1),
            "readme": asset(contract.readme),
        },
    }


def canonical_full_source_bindings_bytes(bindings: Mapping[str, Any]) -> bytes:
    """Serialize source bindings as deterministic canonical JSON plus LF."""
    try:
        return (
            json.dumps(
                dict(bindings),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FullSourceContractError(f"source bindings are not canonical JSON: {exc}") from exc


def verify_full_source_inputs(
    inputs: FullSourceStageInputs,
    *,
    contract: FullSourceStageContract = PRODUCTION_CONTRACT,
) -> dict[str, Any]:
    """Verify every full-source byte, member, row count, and reviewed policy."""
    _verify_archive(inputs.all_countries_zip, contract.all_countries, "allCountries archive")
    _verify_archive(inputs.alternate_names_zip, contract.alternate_names, "alternateNames archive")
    _verify_plain_rows(inputs.admin1, contract.admin1, "admin1 input")
    _verify_file(inputs.readme, contract.readme, "GeoNames readme")
    for path, expected, label in (
        (inputs.source_lock, contract.source_lock_sha256, "source lock"),
        (inputs.catalogue_policy, contract.catalogue_policy_sha256, "catalogue policy"),
        (inputs.normalization_policy, contract.normalization_policy_sha256, "normalization policy"),
    ):
        _require_regular(path, label)
        if _sha256(path)[0] != expected:
            raise FullSourceContractError(f"{label} bytes differ from the reviewed identity")
    load_catalogue_policy(inputs.catalogue_policy)
    load_normalization_policy(inputs.normalization_policy)
    for path, expected, label in (
        (inputs.source_lock, contract.source_lock_sha256, "source lock"),
        (inputs.catalogue_policy, contract.catalogue_policy_sha256, "catalogue policy"),
        (inputs.normalization_policy, contract.normalization_policy_sha256, "normalization policy"),
    ):
        _require_regular(path, label)
        if _sha256(path)[0] != expected:
            raise FullSourceContractError(f"{label} changed while it was being verified")
    return full_source_bindings(contract)
