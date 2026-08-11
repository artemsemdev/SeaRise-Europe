#!/usr/bin/env python3
"""Offline validation of the exact pinned GeoNames alternate-name snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from searise_pipeline.settlements import (
    ALTERNATE_NAMES_SOURCE,
    ISO_LANGUAGE_SOURCE,
    NON_LANGUAGE_NAMESPACES,
    NORMALIZATION_POLICY_VERSION,
    GeoNamesParseError,
    alternate_name_rejection,
    language_codes,
    parse_alternate_name_row,
    parse_iso_language_row,
)

MAX_FAILURE_SIGNATURES = 16
ISO_HEADER = b"ISO 639-3\tISO 639-2\tISO 639-1\tLanguage Name"
SOURCE_LOCK_PATH = "src/pipeline/sources/source-lock.phase-1-settlements.json"
REPORT_COMMAND = (
    "PYTHONPATH=src/pipeline python scripts/release/validate_geonames_alternate_snapshot.py "
    "--source-lock src/pipeline/sources/source-lock.phase-1-settlements.json "
    "--alternate-names-zip <local-verified-cache>/alternateNamesV2.zip "
    "--expected-report "
    "src/pipeline/tests/settlements/fixtures/geonames/alternate-full-scan-report.json"
)


class SnapshotValidationError(ValueError):
    """The lock, source archive, or reviewed report is inconsistent."""


@dataclass(frozen=True)
class LockedMember:
    path: str
    sha256: str
    byte_size: int
    compressed_byte_size: int
    crc32: str


@dataclass(frozen=True)
class LockedAlternateSnapshot:
    lock_sha256: str
    asset_sha256: str
    asset_byte_size: int
    members: tuple[LockedMember, ...]


@dataclass
class FailureTally:
    signatures: Counter[str]
    count: int = 0
    overflow_count: int = 0

    @classmethod
    def empty(cls) -> FailureTally:
        return cls(Counter())

    def add(self, signature: str) -> None:
        self.count += 1
        if (
            signature in self.signatures
            or len(self.signatures) < MAX_FAILURE_SIGNATURES
        ):
            self.signatures[signature] += 1
        else:
            self.overflow_count += 1

    def as_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "overflowCount": self.overflow_count,
            "signatures": dict(sorted(self.signatures.items())),
        }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_members() -> tuple[LockedMember, ...]:
    return tuple(
        LockedMember(
            identity.source_file,
            identity.source_sha256,
            identity.source_byte_size,
            identity.source_compressed_byte_size or 0,
            identity.source_crc32 or "",
        )
        for identity in (ALTERNATE_NAMES_SOURCE, ISO_LANGUAGE_SOURCE)
    )


def _load_locked_snapshot(path: Path) -> LockedAlternateSnapshot:
    raw = path.read_bytes()
    try:
        document = json.loads(raw)
        sources = document["sources"]
        if len(sources) != 1 or sources[0]["id"] != "geonames-settlement-catalogue":
            raise SnapshotValidationError(
                "source lock must contain only the GeoNames snapshot"
            )
        source = sources[0]
        asset = next(
            item for item in source["assets"] if item["id"] == "alternate-names-v2"
        )
        if len(asset["members"]) != 2:
            raise SnapshotValidationError(
                "alternate-name lock must contain exactly two members"
            )
        locked = LockedAlternateSnapshot(
            hashlib.sha256(raw).hexdigest(),
            asset["sha256"],
            asset["byteSize"],
            tuple(
                LockedMember(
                    member["path"],
                    member["sha256"],
                    member["byteSize"],
                    member["compressedByteSize"],
                    member["crc32"],
                )
                for member in asset["members"]
            ),
        )
    except (KeyError, StopIteration, TypeError, json.JSONDecodeError) as exc:
        raise SnapshotValidationError("source lock identity is incomplete") from exc
    expected = LockedAlternateSnapshot(
        locked.lock_sha256,
        ALTERNATE_NAMES_SOURCE.asset_sha256,
        ALTERNATE_NAMES_SOURCE.asset_byte_size,
        _expected_members(),
    )
    if locked != expected or source["version"] != ALTERNATE_NAMES_SOURCE.source_release:
        raise SnapshotValidationError(
            "parser constants differ from the scoped source lock"
        )
    return locked


def _validate_zip_inventory(
    archive: zipfile.ZipFile, locked: LockedAlternateSnapshot
) -> dict[str, zipfile.ZipInfo]:
    entries = archive.infolist()
    expected_paths = {
        ALTERNATE_NAMES_SOURCE.source_file,
        ISO_LANGUAGE_SOURCE.source_file,
    }
    if len(entries) != 2 or {item.filename for item in entries} != expected_paths:
        raise SnapshotValidationError(
            "alternate-name ZIP member inventory is not exact"
        )
    infos = {item.filename: item for item in entries}
    if len(infos) != len(entries):
        raise SnapshotValidationError(
            "alternate-name ZIP member inventory has duplicates"
        )
    locked_by_path = {item.path: item for item in locked.members}
    if set(locked_by_path) != expected_paths:
        raise SnapshotValidationError(
            "locked alternate-name member inventory is not exact"
        )
    for path, info in infos.items():
        member = locked_by_path[path]
        if (info.file_size, info.compress_size, f"{info.CRC:08x}") != (
            member.byte_size,
            member.compressed_byte_size,
            member.crc32,
        ):
            raise SnapshotValidationError(
                f"{path} ZIP member metadata differs from the lock"
            )
    return infos


def _inspect_archive(path: Path, locked: LockedAlternateSnapshot) -> dict[str, object]:
    if (_file_sha256(path), path.stat().st_size) != (
        locked.asset_sha256,
        locked.asset_byte_size,
    ):
        raise SnapshotValidationError(
            "alternate-name asset bytes differ from the scoped lock"
        )

    failures = FailureTally.empty()
    counts: Counter[str] = Counter()
    member_digests: dict[str, hashlib._Hash] = {}  # type: ignore[name-defined]
    with zipfile.ZipFile(path) as archive:
        infos = _validate_zip_inventory(archive, locked)
        language_records = []
        iso_path = ISO_LANGUAGE_SOURCE.source_file
        iso_digest = hashlib.sha256()
        member_digests[iso_path] = iso_digest
        with archive.open(infos[iso_path]) as stream:
            header = stream.readline()
            iso_digest.update(header)
            if header.rstrip(b"\r\n") != ISO_HEADER:
                raise SnapshotValidationError(
                    "iso-languagecodes header differs from the contract"
                )
            for line_number, row in enumerate(stream, 2):
                iso_digest.update(row)
                counts["isoLanguageRows"] += 1
                try:
                    language_records.append(
                        parse_iso_language_row(
                            row.rstrip(b"\r\n"), source_line=line_number
                        )
                    )
                except GeoNamesParseError as exc:
                    failures.add("iso-language: " + str(exc).split(": ", 1)[-1])
                else:
                    counts["isoLanguageRowsParsed"] += 1
                    counts["iso639ThreeOnlyRows"] += bool(
                        language_records[-1].iso639_3
                        and not language_records[-1].iso639_2
                    )
        known_codes = language_codes(language_records)

        alternate_path = ALTERNATE_NAMES_SOURCE.source_file
        alternate_digest = hashlib.sha256()
        member_digests[alternate_path] = alternate_digest
        with archive.open(infos[alternate_path]) as stream:
            for line_number, row in enumerate(stream, 1):
                alternate_digest.update(row)
                counts["alternateNameRows"] += 1
                try:
                    record = parse_alternate_name_row(
                        row.rstrip(b"\r\n"), source_line=line_number
                    )
                except GeoNamesParseError as exc:
                    failures.add(str(exc).split(": ", 1)[-1])
                    continue
                counts["alternateNamesParsedRows"] += 1
                counts["preferredRows"] += record.preferred
                counts["shortRows"] += record.short
                counts["colloquialRows"] += record.colloquial
                counts["historicRows"] += record.historic
                counts["datedRows"] += bool(record.valid_from or record.valid_to)
                if record.language_tag is None:
                    counts["unlabelledNameRows"] += 1
                elif record.language_tag in NON_LANGUAGE_NAMESPACES:
                    counts["nonLanguageNamespaceRows"] += 1
                elif record.language_tag.split("-", 1)[0] in known_codes:
                    counts["languageNameRows"] += 1
                else:
                    failures.add("isoLanguage is absent from locked language metadata")
                for anomaly in record.anomalies:
                    counts[
                        {
                            "edge-ascii-space": "edgeAsciiSpaceNameRows",
                            "empty-source-name": "emptyNameRows",
                            "provider-del-c1-codepoint": "delC1NameRows",
                            "unparseable-from-period": "unparseableFromPeriodRows",
                            "unparseable-to-period": "unparseableToPeriodRows",
                        }[anomaly]
                    ] += 1
                rejection = alternate_name_rejection(
                    record,
                    known_language_codes=known_codes,
                    as_of=date.fromisoformat(ALTERNATE_NAMES_SOURCE.source_release),
                )
                if rejection:
                    counts["normalizationRejectedRows"] += 1
                    counts[
                        "normalizationRejected"
                        + "".join(part.title() for part in rejection.split("-"))
                        + "Rows"
                    ] += 1
                else:
                    counts["normalizationEligibleRows"] += 1

        locked_by_path = {item.path: item for item in locked.members}
        for member_path, digest in member_digests.items():
            if digest.hexdigest() != locked_by_path[member_path].sha256:
                raise SnapshotValidationError(
                    f"{member_path} SHA-256 differs from the lock"
                )

    members = {
        member.path: {
            "sha256": member.sha256,
            "byteSize": member.byte_size,
            "compressedByteSize": member.compressed_byte_size,
            "crc32": member.crc32,
        }
        for member in locked.members
    }
    return {
        "policyVersion": NORMALIZATION_POLICY_VERSION,
        "sourceLockSha256": locked.lock_sha256,
        "archive": {
            "assetSha256": locked.asset_sha256,
            "assetByteSize": locked.asset_byte_size,
        },
        "members": members,
        "counts": dict(sorted((key, value) for key, value in counts.items() if value)),
        "failures": failures.as_dict(),
    }


def inspect_snapshot(archive_path: Path, source_lock_path: Path) -> dict[str, object]:
    return _inspect_archive(archive_path, _load_locked_snapshot(source_lock_path))


def _validate_expected_report(
    actual: dict[str, object], report: dict[str, object]
) -> None:
    if not isinstance(report, dict):
        raise SnapshotValidationError("expected report must be a JSON object")
    source_lock = report.get("sourceLock")
    if (
        set(report)
        != {
            "schemaVersion",
            "evidenceClass",
            "publicationClaim",
            "snapshotDate",
            "sourceLock",
            "command",
            "observation",
            "result",
        }
        or report.get("schemaVersion") != 1
        or report.get("evidenceClass") != "local-offline-source-validation"
        or report.get("publicationClaim") is not False
        or report.get("snapshotDate") != ALTERNATE_NAMES_SOURCE.source_release
        or report.get("command") != REPORT_COMMAND
        or not isinstance(source_lock, dict)
        or set(source_lock) != {"path", "sha256"}
        or source_lock.get("path") != SOURCE_LOCK_PATH
        or source_lock.get("sha256") != actual["sourceLockSha256"]
    ):
        raise SnapshotValidationError(
            "expected report metadata envelope differs from the contract"
        )
    observation = report.get("observation")
    elapsed = (
        observation.get("elapsedSeconds") if isinstance(observation, dict) else None
    )
    if (
        not isinstance(observation, dict)
        or set(observation) != {"environment", "elapsedSeconds"}
        or not isinstance(observation.get("environment"), str)
        or not observation["environment"]
        or isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(elapsed)
        or elapsed < 0
    ):
        raise SnapshotValidationError("expected report observation is malformed")
    if report.get("result") != actual:
        raise SnapshotValidationError(
            "full-snapshot result differs from the reviewed report"
        )
    failures = actual.get("failures")
    if not isinstance(failures, dict) or failures.get("count") != 0:
        raise SnapshotValidationError(
            "full-snapshot parser or language validation failed"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--alternate-names-zip", type=Path, required=True)
    parser.add_argument("--expected-report", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    try:
        actual = inspect_snapshot(args.alternate_names_zip, args.source_lock)
        report = json.loads(args.expected_report.read_text(encoding="utf-8"))
        _validate_expected_report(actual, report)
    except (
        OSError,
        KeyError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
        SnapshotValidationError,
    ) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(actual, indent=2, sort_keys=True))
    print(f"elapsedSeconds={time.monotonic() - started:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
