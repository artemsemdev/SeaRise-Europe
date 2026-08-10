"""Mutation controls for the offline GeoNames full-snapshot validator."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import warnings
import zipfile
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).parents[4]
LOCK_PATH = REPO_ROOT / "src/pipeline/sources/source-lock.phase-1-settlements.json"
REPORT_PATH = Path(__file__).with_name("fixtures") / "geonames/full-scan-report.json"


def _load_validator() -> ModuleType:
    script = REPO_ROOT / "scripts/release/validate_geonames_place_snapshot.py"
    specification = importlib.util.spec_from_file_location(
        "validate_geonames_place_snapshot",
        script,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()
MAX_FAILURE_SIGNATURES = VALIDATOR.MAX_FAILURE_SIGNATURES
FailureTally = VALIDATOR.FailureTally
SnapshotValidationError = VALIDATOR.SnapshotValidationError
_load_locked_snapshot = VALIDATOR._load_locked_snapshot
_validate_expected_report = VALIDATOR._validate_expected_report
_validate_zip_inventory = VALIDATOR._validate_zip_inventory


def test_mutated_scoped_lock_and_report_mismatch_fail_closed(tmp_path: Path) -> None:
    document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    all_countries = next(
        item for item in document["sources"][0]["assets"] if item["id"] == "all-countries"
    )
    all_countries["sha256"] = "0" * 64
    mutated_lock = tmp_path / "source-lock.json"
    mutated_lock.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SnapshotValidationError, match="constants"):
        _load_locked_snapshot(mutated_lock)

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    actual = copy.deepcopy(report["result"])
    report["result"]["counts"]["allCountriesRows"] += 1
    with pytest.raises(SnapshotValidationError, match="differs"):
        _validate_expected_report(actual, report)
    report["result"] = actual
    report["sourceLock"]["sha256"] = "f" * 64
    with pytest.raises(SnapshotValidationError, match="source lock"):
        _validate_expected_report(actual, report)


def _zip_with_members(path: Path, members: list[str]) -> Path:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, member in enumerate(members):
                archive.writestr(member, f"row-{index}\n")
    return path


@pytest.mark.parametrize(
    "members",
    [
        ["allCountries.txt", "extra.txt"],
        ["allCountries.txt", "allCountries.txt"],
        ["./allCountries.txt"],
    ],
)
def test_zip_inventory_rejects_extra_duplicate_and_variant_paths(
    tmp_path: Path, members: list[str]
) -> None:
    archive_path = _zip_with_members(tmp_path / "bad.zip", members)
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(SnapshotValidationError, match="exactly"):
            _validate_zip_inventory(archive, _load_locked_snapshot(LOCK_PATH))


@pytest.mark.parametrize("field", ["member_size", "member_compressed_size", "member_crc32"])
def test_zip_inventory_rejects_wrong_locked_member_metadata(tmp_path: Path, field: str) -> None:
    archive_path = _zip_with_members(tmp_path / "one.zip", ["allCountries.txt"])
    locked = _load_locked_snapshot(LOCK_PATH)
    with zipfile.ZipFile(archive_path) as archive:
        info = archive.infolist()[0]
        matching = replace(
            locked,
            member_size=info.file_size,
            member_compressed_size=info.compress_size,
            member_crc32=f"{info.CRC:08x}",
        )
        mutation = "00000000" if field == "member_crc32" else getattr(matching, field) + 1
        with pytest.raises(SnapshotValidationError, match="metadata"):
            _validate_zip_inventory(archive, replace(matching, **{field: mutation}))


def test_failure_signatures_have_a_deterministic_overflow_cap() -> None:
    failures = FailureTally.empty()
    for index in range(MAX_FAILURE_SIGNATURES + 2):
        failures.add(f"signature-{index:02d}")
    failures.add("signature-00")
    assert failures.as_dict() == {
        "count": MAX_FAILURE_SIGNATURES + 3,
        "overflowCount": 2,
        "signatures": {
            **{f"signature-{index:02d}": 1 for index in range(MAX_FAILURE_SIGNATURES)},
            "signature-00": 2,
        },
    }
