"""Validate the real-source Baltic and Black Sea control evidence."""

from __future__ import annotations

import gzip
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from scripts.science import build_basin_control_evidence as evidence_builder
from scripts.science.build_basin_control_evidence import (
    EvidenceBuildError,
    _canonical_bytes,
    validate_checked_in_evidence,
)

REPO_ROOT = Path(__file__).parents[4]
SCIENCE_DIR = REPO_ROOT / "src/pipeline/science"
CONTRACT_PATH = SCIENCE_DIR / "basin-controls.json"
SCHEMA_PATH = SCIENCE_DIR / "basin-controls.schema.json"
EVIDENCE_PATH = SCIENCE_DIR / "evidence/phase-0-12-basin-controls.json"
EVIDENCE_SCHEMA_PATH = (
    SCIENCE_DIR / "evidence/phase-0-12-basin-controls.schema.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_basin_control_contract_is_strict_and_fail_closed() -> None:
    contract = _load(CONTRACT_PATH)
    schema = _load(SCHEMA_PATH)

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(contract)

    assert contract["status"] == "source-pinning-complete-vertical-goldens-blocked"
    assert contract["sourcePolicy"] == {
        "scientificInputs": "real-source-only",
        "baselineSampling": "source-native-cell-centres-no-extrapolation",
        "landAndNodata": "DataUnavailable:source-nodata",
        "unsupportedDomain": "blocked-or-UnsupportedGeography-never-extrapolated",
        "modelIndependence": "expectations-must-not-be-generated-by-vertical-classifier",
    }
    assert {window["basin"] for window in contract["windows"]} == {
        "Baltic Sea",
        "Black Sea",
    }
    assert len(contract["windows"]) == 4
    assert contract["publicationGate"] == {
        "status": "blocked",
        "europeWideClaimAllowed": False,
        "blockingIssues": [94, 95, 97],
    }


def test_exact_five_layer_basin_manifest_is_standalone_and_validated() -> None:
    contract = _load(CONTRACT_PATH)
    descriptor = contract["sourceBindings"]["terrain"]
    manifest_path = REPO_ROOT / descriptor["manifestPath"]
    compressed = manifest_path.read_bytes()
    payload = gzip.decompress(compressed)
    records = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    header, rows = records[0], records[1:]

    assert len(compressed) == descriptor["manifestByteSize"] == 1641
    assert hashlib.sha256(compressed).hexdigest() == descriptor["manifestSha256"]
    assert hashlib.sha256(payload).hexdigest() == descriptor["payloadSha256"]
    assert header["objectCount"] == descriptor["objectCount"] == len(rows) == 20
    assert header["totalByteSize"] == descriptor["totalByteSize"] == 224337149
    assert set(header["regions"]) == {
        "gdansk-vistula",
        "stockholm-archipelago",
        "constanta-black-sea",
        "batumi-black-sea-boundary",
    }
    assert {(row["region"], row["role"]) for row in rows} == {
        (region, layer)
        for region in header["regions"]
        for layer in ("DEM", "EDM", "FLM", "HEM", "WBM")
    }
    assert all(len(row["sha256"]) == 64 for row in rows)
    assert all(
        row["url"] == descriptor["resolvedUrl"] + "/" + row["key"]
        for row in rows
    )
    assert descriptor["licence"]["redistributionStatus"] == "approved"


def test_all_reference_period_inputs_are_verified_at_native_cells() -> None:
    evidence = _load(EVIDENCE_PATH)
    baseline = evidence["baseline"]

    assert baseline["sla"]["assetCount"] == 240
    assert baseline["sla"]["allAssetsVerified"] is True
    assert baseline["sla"]["sourceGrid"] == {
        "shape": [738, 1154],
        "longitude": {
            "minimum": -30.03125,
            "maximum": 42.03125,
            "spacingDegrees": 0.0625,
        },
        "latitude": {
            "minimum": 19.96875,
            "maximum": 66.03125,
            "spacingDegrees": 0.0625,
        },
    }
    assert baseline["mdt"]["sha256"] == (
        "397cdca04e899ceb9eb3182f87cab64498357881407b3ab769796ce756249682"
    )

    expected = {
        "gdansk-vistula": (111, 145, 0),
        "stockholm-archipelago": (127, 129, 17),
        "constanta-black-sea": (73, 183, 1),
        "batumi-black-sea-boundary": (123, 133, 5),
    }
    for window_id, (ready, unavailable, mask_disagreements) in expected.items():
        window = baseline["windows"][window_id]
        assert window["sourceCellCount"] == 256
        assert window["baselineReady"] == ready
        assert window["baselineUnavailable"] == unavailable
        assert window["slaReadyMdtNodata"] == mask_disagreements
        assert window["slaPartiallyValidMonths"] == 0
        assert window["extrapolatedCellCount"] == 0
        assert window["missingRule"] == "DataUnavailable:source-nodata"


def test_real_dem_and_quality_layers_cover_every_new_window() -> None:
    evidence = _load(EVIDENCE_PATH)
    terrain = evidence["terrain"]

    assert terrain["manifestAssetsVerified"] == 20
    assert set(terrain["windows"]) == {
        "gdansk-vistula",
        "stockholm-archipelago",
        "constanta-black-sea",
        "batumi-black-sea-boundary",
    }
    for window in terrain["windows"].values():
        assert set(window["assets"]) == {"DEM", "EDM", "FLM", "HEM", "WBM"}
        assert all(len(asset["sha256"]) == 64 for asset in window["assets"].values())
        assert window["grid"]["horizontalCrs"] == "EPSG:4326"
        assert window["grid"]["pixelInterpretation"] == "Point"
        assert window["grid"]["latitudeSpacingArcSeconds"] == 1.0
        assert window["quality"]["heightError"]["validLandPixelCount"] > 0
        assert window["quality"]["heightError"]["sentinelPixelCount"] > 0


def test_combined_suite_reserves_and_verifies_all_five_states() -> None:
    contract = _load(CONTRACT_PATH)
    evidence = _load(EVIDENCE_PATH)
    expectations = evidence["combinedSuite"]["stateExpectations"]

    assert evidence["combinedSuite"]["totalWindowCount"] == 9
    assert {item["expectedState"] for item in expectations} == {
        "ModeledExposureDetected",
        "NoModeledExposureDetected",
        "DataUnavailable",
        "OutOfScope",
        "UnsupportedGeography",
    }
    pending = [item for item in expectations if item["actualState"] is None]
    assert {item["expectedState"] for item in pending} == {
        "ModeledExposureDetected",
        "NoModeledExposureDetected",
    }
    assert all(item["passed"] is None for item in pending)
    assert all(
        item["verificationStatus"] == "blocked-pending-independent-executable-golden"
        for item in pending
    )
    verified = [item for item in expectations if item["actualState"] is not None]
    assert all(item["passed"] is True for item in verified)
    assert all(item["actualState"] == item["expectedState"] for item in verified)
    assert all(
        item["provenance"]["generatedByModelUnderTest"] is False
        for item in contract["combinedSuite"]["stateExpectations"]
    )


def test_connectivity_results_are_not_fabricated_before_dependencies_pass() -> None:
    evidence = _load(EVIDENCE_PATH)

    assert evidence["connectivityComparison"] == {
        "status": "not-run-fail-closed",
        "unfilteredCount": None,
        "connectedCount": None,
        "removedCount": None,
        "disagreementCount": None,
        "blockedBy": [94, 95, 97],
    }
    assert evidence["review"]["status"] == "pending-external"
    assert evidence["publicationGate"]["europeWideClaimAllowed"] is False


def test_evidence_is_compact_canonical_and_licence_complete() -> None:
    raw = EVIDENCE_PATH.read_bytes()
    evidence = json.loads(raw)
    canonical = (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode()

    assert raw == canonical
    assert len(raw) < 20_000
    assert evidence["realSourceOnly"] is True
    assert evidence["sourceAndLicence"]["rawAssetsCommitted"] is False
    licences = evidence["sourceAndLicence"]["licences"]
    assert {item["sourceId"] for item in licences} == {
        "ipcc-ar6-sea-level",
        "copernicus-marine-eur-sla-monthly",
        "copernicus-marine-eur-mdt",
        "goco06s-gravity-model",
        "egm2008-gravity-model",
        "copernicus-dem-glo30",
        "natural-earth-10m",
    }
    assert all(item["redistributionStatus"] == "approved" for item in licences)
    assert all(item["name"] and item["url"] and item["attribution"] for item in licences)


def test_evidence_schema_and_validator_enforce_the_checked_in_receipt() -> None:
    evidence = _load(EVIDENCE_PATH)
    schema = _load(EVIDENCE_SCHEMA_PATH)

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(evidence)
    assert validate_checked_in_evidence(REPO_ROOT) == evidence
    assert _canonical_bytes(evidence) == EVIDENCE_PATH.read_bytes()
    assert set(evidence["lineage"]) == {
        "recipe",
        "contract",
        "contractSchema",
        "evidenceSchema",
        "sourceLock",
        "sourceLockSchema",
        "supportGeometry",
        "coastalGeometry",
        "connectivityControls",
        "slaManifest",
        "terrainManifest",
        "existingTerrainManifest",
    }


def test_builder_regenerates_receipt_bytes_from_recorded_measurements(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence = _load(EVIDENCE_PATH)
    contract = _load(CONTRACT_PATH)
    sla_manifest = REPO_ROOT / evidence["lineage"]["slaManifest"]["path"]
    monthly_header, monthly_rows, _ = evidence_builder._manifest_records(sla_manifest)

    monkeypatch.setattr(
        evidence_builder,
        "_verify_monthly_inputs",
        lambda *_: (monthly_rows, monthly_header),
    )
    monkeypatch.setattr(
        evidence_builder,
        "_inspect_baseline",
        lambda *_: (evidence["baseline"], evidence["marineAnchors"]),
    )
    monkeypatch.setattr(
        evidence_builder,
        "_inspect_dem_controls",
        lambda *_: evidence["terrain"]["windows"],
    )
    monkeypatch.setattr(
        evidence_builder,
        "_inspect_state_expectations",
        lambda *_: evidence["combinedSuite"]["stateExpectations"],
    )

    rebuilt = evidence_builder.build_evidence(
        REPO_ROOT,
        contract,
        tmp_path / "dem",
        tmp_path / "monthly-sla",
        tmp_path / "mdt.nc",
    )

    assert _canonical_bytes(rebuilt) == EVIDENCE_PATH.read_bytes()


@pytest.mark.parametrize(
    "lineage_key",
    [
        "recipe",
        "contract",
        "contractSchema",
        "evidenceSchema",
        "sourceLock",
        "sourceLockSchema",
        "supportGeometry",
        "coastalGeometry",
        "connectivityControls",
        "slaManifest",
        "terrainManifest",
        "existingTerrainManifest",
    ],
)
def test_validator_recomputes_every_committed_lineage_binding(
    tmp_path: Path, lineage_key: str
) -> None:
    evidence = deepcopy(_load(EVIDENCE_PATH))
    evidence["lineage"][lineage_key]["sha256"] = "0" * 64
    receipt = tmp_path / "mutated-receipt.json"
    receipt.write_bytes(_canonical_bytes(evidence))

    with pytest.raises(EvidenceBuildError, match="identity mismatch"):
        validate_checked_in_evidence(REPO_ROOT, receipt)


def test_validator_recomputes_manifest_payload_and_summary(tmp_path: Path) -> None:
    evidence = deepcopy(_load(EVIDENCE_PATH))
    evidence["lineage"]["terrainManifest"]["payloadSha256"] = "0" * 64
    receipt = tmp_path / "mutated-manifest-lineage.json"
    receipt.write_bytes(_canonical_bytes(evidence))

    with pytest.raises(EvidenceBuildError, match="payload identity mismatch"):
        validate_checked_in_evidence(REPO_ROOT, receipt)


def test_validator_rejects_noncanonical_or_extended_receipts(tmp_path: Path) -> None:
    evidence = deepcopy(_load(EVIDENCE_PATH))
    evidence["unexpectedClaim"] = True
    receipt = tmp_path / "extended-receipt.json"
    receipt.write_bytes(_canonical_bytes(evidence))
    with pytest.raises(EvidenceBuildError, match="Additional properties"):
        validate_checked_in_evidence(REPO_ROOT, receipt)

    noncanonical = tmp_path / "noncanonical-receipt.json"
    noncanonical.write_text(json.dumps(_load(EVIDENCE_PATH), indent=2) + "\n")
    with pytest.raises(EvidenceBuildError, match="byte-identical canonical JSON"):
        validate_checked_in_evidence(REPO_ROOT, noncanonical)
