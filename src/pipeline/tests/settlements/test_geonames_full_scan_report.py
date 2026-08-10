"""Bind the offline full-snapshot scan report to its parser and source lock."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from searise_pipeline.settlements import (
    ADMIN1_SOURCE,
    ALL_COUNTRIES_SOURCE,
    RAW_ANOMALY_POLICY_VERSION,
)

FIXTURE_DIR = Path(__file__).with_name("fixtures") / "geonames"
REPO_ROOT = Path(__file__).parents[4]
REPORT = json.loads((FIXTURE_DIR / "full-scan-report.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((FIXTURE_DIR / "fixture-manifest.json").read_text(encoding="utf-8"))


def _load_validator() -> ModuleType:
    script = REPO_ROOT / "scripts/release/validate_geonames_place_snapshot.py"
    specification = importlib.util.spec_from_file_location(
        "validate_geonames_place_snapshot_report",
        script,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


inspect_snapshot = _load_validator().inspect_snapshot


def test_full_scan_report_is_local_only_hash_bound_and_anomaly_exact() -> None:
    assert REPORT["evidenceClass"] == "local-offline-source-validation"
    assert REPORT["publicationClaim"] is False
    assert callable(inspect_snapshot)
    assert "scripts/release/validate_geonames_place_snapshot.py" in REPORT["command"]
    assert (
        "--source-lock src/pipeline/sources/source-lock.phase-1-settlements.json"
        in REPORT["command"]
    )
    assert REPORT["sourceLock"] == MANIFEST["sourceLock"]
    lock_path = REPO_ROOT / REPORT["sourceLock"]["path"]
    assert hashlib.sha256(lock_path.read_bytes()).hexdigest() == REPORT["sourceLock"]["sha256"]
    result = REPORT["result"]
    assert result["policyVersion"] == RAW_ANOMALY_POLICY_VERSION
    assert result["sourceLockSha256"] == REPORT["sourceLock"]["sha256"]
    assert result["allCountries"] == {
        "assetSha256": ALL_COUNTRIES_SOURCE.asset_sha256,
        "assetByteSize": ALL_COUNTRIES_SOURCE.asset_byte_size,
        "memberSha256": ALL_COUNTRIES_SOURCE.source_sha256,
        "memberByteSize": ALL_COUNTRIES_SOURCE.source_byte_size,
        "memberCompressedByteSize": ALL_COUNTRIES_SOURCE.source_compressed_byte_size,
        "memberCrc32": ALL_COUNTRIES_SOURCE.source_crc32,
    }
    assert result["admin1"] == {
        "assetSha256": ADMIN1_SOURCE.asset_sha256,
        "assetByteSize": ADMIN1_SOURCE.asset_byte_size,
    }
    assert result["failures"] == {"count": 0, "overflowCount": 0, "signatures": {}}
    assert result["counts"] | {"failures": result["failures"]["count"]} == {
        "admin1ParsedRows": 3865,
        "admin1Rows": 3865,
        "allCountriesParsedRows": 13455006,
        "allCountriesRows": 13455006,
        "delC1AliasRows": 32,
        "delC1NameRows": 3,
        "edgeAsciiSpaceAliasRows": 588,
        "leadingEmptyAlternateCountryRows": 4,
        "negativePlacePopulationRows": 0,
        "negativePopulationRows": 2,
        "nullFeatureClassRows": 5003,
        "nullFeatureCodeRows": 94937,
        "nullPopulationRows": 0,
        "placeNullAdmin1Rows": 967,
        "placeRows": 5220666,
        "failures": 0,
    }
