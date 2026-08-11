"""Mutation and immutable-report checks for the alternate-name snapshot scan."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import warnings
import zipfile
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from searise_pipeline.settlements import (
    ALTERNATE_NAMES_SOURCE,
    ISO_LANGUAGE_SOURCE,
    NORMALIZATION_POLICY_VERSION,
)

REPO_ROOT = Path(__file__).parents[4]
FIXTURE_DIR = Path(__file__).with_name("fixtures") / "geonames"
LOCK_PATH = REPO_ROOT / "src/pipeline/sources/source-lock.phase-1-settlements.json"
REPORT_PATH = FIXTURE_DIR / "alternate-full-scan-report.json"


def _load_validator() -> ModuleType:
    script = REPO_ROOT / "scripts/release/validate_geonames_alternate_snapshot.py"
    specification = importlib.util.spec_from_file_location(
        "validate_geonames_alternate_snapshot", script
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()
LockedAlternateSnapshot = VALIDATOR.LockedAlternateSnapshot
LockedMember = VALIDATOR.LockedMember
SnapshotValidationError = VALIDATOR.SnapshotValidationError
_inspect_archive = VALIDATOR._inspect_archive
_load_locked_snapshot = VALIDATOR._load_locked_snapshot
_validate_expected_report = VALIDATOR._validate_expected_report
_validate_zip_inventory = VALIDATOR._validate_zip_inventory


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_archive(path: Path, *, extra: bool = False) -> Path:
    alternate = (FIXTURE_DIR / "alternateNamesV2.rows.txt").read_bytes()
    languages = (FIXTURE_DIR / "iso-languagecodes.rows.txt").read_bytes()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "iso-languagecodes.txt",
                b"ISO 639-3\tISO 639-2\tISO 639-1\tLanguage Name\r\n" + languages,
            )
            archive.writestr("alternateNamesV2.txt", alternate)
            if extra:
                archive.writestr("extra.txt", b"unexpected\n")
    return path


def _locked_fixture(path: Path) -> LockedAlternateSnapshot:
    with zipfile.ZipFile(path) as archive:
        members = tuple(
            LockedMember(
                info.filename,
                hashlib.sha256(archive.read(info)).hexdigest(),
                info.file_size,
                info.compress_size,
                f"{info.CRC:08x}",
            )
            for info in archive.infolist()
        )
    return LockedAlternateSnapshot("f" * 64, _sha256(path), path.stat().st_size, members)


def test_fixture_archive_exercises_both_locked_members_and_policy_counts(tmp_path: Path) -> None:
    archive = _fixture_archive(tmp_path / "fixture.zip")
    result = _inspect_archive(archive, _locked_fixture(archive))
    assert result["policyVersion"] == NORMALIZATION_POLICY_VERSION
    assert result["counts"] == {
        "alternateNameRows": 12,
        "alternateNamesParsedRows": 12,
        "colloquialRows": 1,
        "datedRows": 2,
        "historicRows": 1,
        "isoLanguageRows": 8,
        "isoLanguageRowsParsed": 8,
        "languageNameRows": 11,
        "nonLanguageNamespaceRows": 1,
        "normalizationEligibleRows": 10,
        "normalizationRejectedHistoricNameRows": 1,
        "normalizationRejectedNonLanguageNamespaceRows": 1,
        "normalizationRejectedRows": 2,
        "preferredRows": 5,
        "shortRows": 3,
    }
    assert result["failures"] == {"count": 0, "overflowCount": 0, "signatures": {}}


def test_lock_and_zip_inventory_mutations_fail_closed(tmp_path: Path) -> None:
    document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    asset = next(
        item for item in document["sources"][0]["assets"] if item["id"] == "alternate-names-v2"
    )
    asset["members"][0]["sha256"] = "0" * 64
    mutated_lock = tmp_path / "source-lock.json"
    mutated_lock.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SnapshotValidationError, match="constants"):
        _load_locked_snapshot(mutated_lock)

    archive = _fixture_archive(tmp_path / "extra.zip", extra=True)
    with zipfile.ZipFile(archive) as opened:
        with pytest.raises(SnapshotValidationError, match="inventory"):
            _validate_zip_inventory(opened, _locked_fixture(archive))

    clean = _fixture_archive(tmp_path / "clean.zip")
    locked = _locked_fixture(clean)
    with zipfile.ZipFile(clean) as opened:
        member = locked.members[0]
        changed = replace(member, crc32="00000000")
        with pytest.raises(SnapshotValidationError, match="metadata"):
            _validate_zip_inventory(opened, replace(locked, members=(changed, locked.members[1])))


def test_full_scan_report_is_local_only_hash_bound_and_exact() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert report["evidenceClass"] == "local-offline-source-validation"
    assert report["publicationClaim"] is False
    assert "validate_geonames_alternate_snapshot.py" in report["command"]
    assert hashlib.sha256(LOCK_PATH.read_bytes()).hexdigest() == report["sourceLock"]["sha256"]
    result = report["result"]
    assert result["policyVersion"] == NORMALIZATION_POLICY_VERSION
    assert result["archive"] == {
        "assetSha256": ALTERNATE_NAMES_SOURCE.asset_sha256,
        "assetByteSize": ALTERNATE_NAMES_SOURCE.asset_byte_size,
    }
    assert (
        result["members"]["alternateNamesV2.txt"]["sha256"] == ALTERNATE_NAMES_SOURCE.source_sha256
    )
    assert result["members"]["iso-languagecodes.txt"]["sha256"] == ISO_LANGUAGE_SOURCE.source_sha256
    assert result["counts"]["alternateNameRows"] == 19037112
    assert result["counts"]["alternateNamesParsedRows"] == 19037112
    assert result["counts"]["isoLanguageRows"] == 7929
    assert result["counts"]["isoLanguageRowsParsed"] == 7929
    assert result["failures"] == {"count": 0, "overflowCount": 0, "signatures": {}}


def test_reviewed_report_binding_rejects_count_drift() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    actual = copy.deepcopy(report["result"])
    report["result"]["counts"]["alternateNameRows"] += 1
    with pytest.raises(SnapshotValidationError, match="differs"):
        _validate_expected_report(actual, report)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("publicationClaim",), True),
        (("evidenceClass",), "publication-validation"),
        (("snapshotDate",), "2099-01-01"),
        (("sourceLock", "path"), "wrong-lock.json"),
        (("command",), "python other.py"),
    ],
)
def test_reviewed_report_binding_rejects_metadata_tampering(
    path: tuple[str, ...], value: object
) -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    actual = copy.deepcopy(report["result"])
    target = report
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(SnapshotValidationError, match="metadata envelope"):
        _validate_expected_report(actual, report)


def test_reviewed_report_binding_rejects_malformed_observation() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    actual = copy.deepcopy(report["result"])
    report["observation"]["elapsedSeconds"] = float("nan")
    with pytest.raises(SnapshotValidationError, match="observation"):
        _validate_expected_report(actual, report)
