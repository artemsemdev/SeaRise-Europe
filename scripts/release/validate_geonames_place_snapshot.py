"""Offline validation of the exact pinned GeoNames place/admin1 snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from searise_pipeline.settlements import (
    ADMIN1_SOURCE,
    ALL_COUNTRIES_SOURCE,
    RAW_ANOMALY_POLICY_VERSION,
    GeoNamesParseError,
    parse_admin1_row,
    parse_geoname_row,
)

MAX_FAILURE_SIGNATURES = 16


class SnapshotValidationError(ValueError):
    """The lock, source archive, or reviewed report is inconsistent."""


@dataclass(frozen=True)
class LockedSnapshot:
    lock_sha256: str
    all_asset_sha256: str
    all_asset_size: int
    member_path: str
    member_sha256: str
    member_size: int
    member_compressed_size: int
    member_crc32: str
    admin_path: str
    admin_sha256: str
    admin_size: int


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


def _load_locked_snapshot(path: Path) -> LockedSnapshot:
    raw = path.read_bytes()
    try:
        document = json.loads(raw)
        sources = document["sources"]
        if len(sources) != 1 or sources[0]["id"] != "geonames-settlement-catalogue":
            raise SnapshotValidationError(
                "source lock must contain only the GeoNames snapshot"
            )
        source = sources[0]
        if source["version"] != source["snapshotDate"]:
            raise SnapshotValidationError("GeoNames version and snapshot date differ")
        assets = {item["id"]: item for item in source["assets"]}
        if len(assets) != len(source["assets"]):
            raise SnapshotValidationError("source lock has duplicate asset ids")
        all_asset = assets[ALL_COUNTRIES_SOURCE.asset_id]
        admin = assets[ADMIN1_SOURCE.asset_id]
        members = all_asset["members"]
        if len(members) != 1:
            raise SnapshotValidationError(
                "allCountries lock must contain exactly one member"
            )
        member = members[0]
        locked = LockedSnapshot(
            hashlib.sha256(raw).hexdigest(),
            all_asset["sha256"],
            all_asset["byteSize"],
            member["path"],
            member["sha256"],
            member["byteSize"],
            member["compressedByteSize"],
            member["crc32"],
            admin["cachePath"],
            admin["sha256"],
            admin["byteSize"],
        )
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SnapshotValidationError("source lock identity is incomplete") from exc
    expected = LockedSnapshot(
        locked.lock_sha256,
        ALL_COUNTRIES_SOURCE.asset_sha256,
        ALL_COUNTRIES_SOURCE.asset_byte_size,
        ALL_COUNTRIES_SOURCE.source_file,
        ALL_COUNTRIES_SOURCE.source_sha256,
        ALL_COUNTRIES_SOURCE.source_byte_size,
        ALL_COUNTRIES_SOURCE.source_compressed_byte_size or 0,
        ALL_COUNTRIES_SOURCE.source_crc32 or "",
        ADMIN1_SOURCE.source_file,
        ADMIN1_SOURCE.source_sha256,
        ADMIN1_SOURCE.source_byte_size,
    )
    if locked != expected or source["version"] != ALL_COUNTRIES_SOURCE.source_release:
        raise SnapshotValidationError(
            "parser constants differ from the scoped source lock"
        )
    return locked


def _validate_zip_inventory(
    archive: zipfile.ZipFile, locked: LockedSnapshot
) -> zipfile.ZipInfo:
    entries = archive.infolist()
    if len(entries) != 1 or entries[0].filename != locked.member_path:
        raise SnapshotValidationError(
            "allCountries ZIP must contain exactly its locked member path"
        )
    info = entries[0]
    actual = (info.file_size, info.compress_size, f"{info.CRC:08x}")
    expected = (locked.member_size, locked.member_compressed_size, locked.member_crc32)
    if actual != expected:
        raise SnapshotValidationError(
            "allCountries ZIP member metadata differs from the lock"
        )
    return info


def inspect_snapshot(
    all_countries_zip: Path, admin1_path: Path, source_lock_path: Path
) -> dict[str, object]:
    locked = _load_locked_snapshot(source_lock_path)
    if (
        _file_sha256(all_countries_zip),
        all_countries_zip.stat().st_size,
        _file_sha256(admin1_path),
        admin1_path.stat().st_size,
    ) != (
        locked.all_asset_sha256,
        locked.all_asset_size,
        locked.admin_sha256,
        locked.admin_size,
    ):
        raise SnapshotValidationError("source asset bytes differ from the scoped lock")

    failures = FailureTally.empty()
    counts: Counter[str] = Counter()
    member_digest = hashlib.sha256()
    with zipfile.ZipFile(all_countries_zip) as archive:
        info = _validate_zip_inventory(archive, locked)
        with archive.open(info) as stream:
            for line_number, row in enumerate(stream, 1):
                member_digest.update(row)
                counts["allCountriesRows"] += 1
                try:
                    record = parse_geoname_row(
                        row.rstrip(b"\n"), source_line=line_number
                    )
                except GeoNamesParseError as exc:
                    failures.add(str(exc).split(": ", 1)[-1])
                    continue
                counts["allCountriesParsedRows"] += 1
                counts["nullFeatureClassRows"] += record.feature_class is None
                counts["nullFeatureCodeRows"] += record.feature_code is None
                counts["nullPopulationRows"] += record.population is None
                if record.feature_class == "P":
                    counts["placeRows"] += 1
                    counts["placeNullAdmin1Rows"] += record.admin1_code is None
                    counts["negativePlacePopulationRows"] += bool(
                        record.population is not None and record.population < 0
                    )
                for anomaly in record.anomalies:
                    key = {
                        ("name", "provider-del-c1-codepoint"): "delC1NameRows",
                        (
                            "convenience_alternate_names",
                            "provider-del-c1-codepoint",
                        ): "delC1AliasRows",
                        (
                            "convenience_alternate_names",
                            "edge-ascii-space",
                        ): "edgeAsciiSpaceAliasRows",
                        (
                            "alternate_country_codes",
                            "leading-empty-source-token",
                        ): "leadingEmptyAlternateCountryRows",
                        (
                            "population",
                            "negative-source-value",
                        ): "negativePopulationRows",
                    }[(anomaly.field, anomaly.code)]
                    counts[key] += 1
    if member_digest.hexdigest() != locked.member_sha256:
        raise SnapshotValidationError(
            "allCountries member SHA-256 differs from the lock"
        )

    with admin1_path.open("rb") as stream:
        for line_number, row in enumerate(stream, 1):
            counts["admin1Rows"] += 1
            try:
                parse_admin1_row(row.rstrip(b"\n"), source_line=line_number)
            except GeoNamesParseError as exc:
                failures.add("admin1: " + str(exc).split(": ", 1)[-1])
            else:
                counts["admin1ParsedRows"] += 1
    return {
        "policyVersion": RAW_ANOMALY_POLICY_VERSION,
        "sourceLockSha256": locked.lock_sha256,
        "allCountries": {
            "assetSha256": locked.all_asset_sha256,
            "assetByteSize": locked.all_asset_size,
            "memberSha256": member_digest.hexdigest(),
            "memberByteSize": info.file_size,
            "memberCompressedByteSize": info.compress_size,
            "memberCrc32": f"{info.CRC:08x}",
        },
        "admin1": {
            "assetSha256": locked.admin_sha256,
            "assetByteSize": locked.admin_size,
        },
        "counts": dict(sorted(counts.items())),
        "failures": failures.as_dict(),
    }


def _validate_expected_report(
    actual: dict[str, object], report: dict[str, object]
) -> None:
    source_lock = report.get("sourceLock")
    if (
        not isinstance(source_lock, dict)
        or source_lock.get("sha256") != actual["sourceLockSha256"]
    ):
        raise SnapshotValidationError(
            "expected report is not bound to the loaded source lock"
        )
    if report.get("result") != actual:
        raise SnapshotValidationError(
            "full-snapshot result differs from the reviewed report"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--all-countries-zip", type=Path, required=True)
    parser.add_argument("--admin1", type=Path, required=True)
    parser.add_argument("--expected-report", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    try:
        actual = inspect_snapshot(args.all_countries_zip, args.admin1, args.source_lock)
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
