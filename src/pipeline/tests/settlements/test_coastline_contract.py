"""Contract tests for the immutable settlement shoreline policy."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from searise_pipeline.settlements.coastline_contract import (
    CoastlineContractError,
    load_coastline_policy,
    quantize_distance_meters,
    sha256_file,
    validate_coastline_sources,
)
from searise_pipeline.sources.registry import load_registry

REPO_ROOT = Path(__file__).parents[4]
POLICY_PATH = REPO_ROOT / "src/pipeline/settlements/shoreline-distance-policy-v1.json"
POLICY_SCHEMA_PATH = REPO_ROOT / "src/pipeline/settlements/shoreline-distance-policy-v1.schema.json"
SOURCE_LOCK_PATH = REPO_ROOT / "src/pipeline/sources/source-lock.phase-1-settlement-coastline.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")


def test_policy_binds_direct_sources_method_and_claim_boundary() -> None:
    registry = load_registry(SOURCE_LOCK_PATH)
    policy = load_coastline_policy(POLICY_PATH, POLICY_SCHEMA_PATH)
    schema = _json(POLICY_SCHEMA_PATH)
    source = registry.sources[0]
    assets = {asset.id: asset for asset in source.assets}

    assert schema["$id"] == "urn:searise-europe:internal:settlement-shoreline-distance-policy:v1"
    assert sha256_file(REPO_ROOT / "src/pipeline/sources/source-lock.json") == (
        "d1f819b7338f90abac0b76dda06cb6779d3231ebedcac54ef9ab78dc7f821066"
    )
    assert policy["sourceLock"]["sha256"] == sha256_file(SOURCE_LOCK_PATH)
    assert (source.id, source.version) == ("natural-earth-10m", "5.1.1")
    assert set(assets) == {"coastline", "minor-islands-coastline"}
    assert all(asset.resolved_version == "5.1.1" for asset in assets.values())
    assert all(len(asset.members) == 7 for asset in assets.values())
    assert [(item["assetId"], item["nativeVersion"]) for item in policy["source"]["assets"]] == [
        ("coastline", "5.0.0-pre9"),
        ("minor-islands-coastline", "4.1.0"),
    ]
    assert policy["distanceMethodVersion"] == "epsg3035-planar-whole-meter-half-even-v1"
    assert policy["distancePersistence"] == {
        "expression": "CAST(ST_Distance(place_3035, shoreline_3035) AS BIGINT)",
        "field": "distance_to_coast_m",
        "inputType": "DOUBLE",
        "outputType": "BIGINT",
        "roundingMode": "nearest-half-to-even",
        "subMeterPrecisionClaim": False,
        "unit": "whole-meter",
    }
    assert policy["purpose"] == {
        "canonicalCoastlineClaim": False,
        "hazardExtentClaim": False,
        "ownerApprovalClaim": False,
        "productEligibilityOnly": True,
        "publicationEligible": False,
        "role": "settlement-distance-to-coast-only",
        "status": "selected-scope-approximation",
    }
    validate_coastline_sources(SOURCE_LOCK_PATH, policy)


@pytest.mark.parametrize(
    ("distance", "expected"),
    [(0.0, 0), (0.5, 0), (1.5, 2), (2.5, 2), (3.5, 4), (2916.2245, 2916)],
)
def test_whole_meter_quantization_uses_nearest_half_even(distance: float, expected: int) -> None:
    assert quantize_distance_meters(distance) == expected


@pytest.mark.parametrize("distance", [-1.0, float("inf"), float("-inf"), float("nan"), True, False])
def test_whole_meter_quantization_rejects_invalid_distance(distance: object) -> None:
    with pytest.raises(CoastlineContractError):
        quantize_distance_meters(distance)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (("purpose", "hazardExtentClaim"), True),
        (("purpose", "status"), "canonical"),
        (("purpose", "ownerApprovalClaim"), True),
        (("purpose", "publicationEligible"), True),
        (("recipe", "inputGeometry"), "ocean-polygon-boundary"),
        (("recipe", "selectionOperation"), "intersection(source-linework,bbox)"),
        (("distancePersistence", "outputType"), "DOUBLE"),
        (("distancePersistence", "unit"), "sub-meter"),
        (("distancePersistence", "roundingMode"), "nearest-half-away-from-zero"),
        (("distancePersistence", "expression"), "ROUND(distance_meters)"),
        (("distancePersistence", "subMeterPrecisionClaim"), True),
        (("distanceMethodVersion",), "unversioned-distance"),
    ],
)
def test_policy_mutations_fail_closed(
    tmp_path: Path, field: tuple[str, ...], value: object
) -> None:
    document = deepcopy(_json(POLICY_PATH))
    if len(field) == 1:
        document[field[0]] = value
    else:
        document[field[0]][field[1]] = value
    path = tmp_path / POLICY_PATH.name
    _write_json(path, document)

    with pytest.raises(CoastlineContractError):
        load_coastline_policy(path, POLICY_SCHEMA_PATH)


@pytest.mark.parametrize("mutation", ["native-version", "archive-sha", "member-sha"])
def test_source_identity_mutations_fail_closed(tmp_path: Path, mutation: str) -> None:
    policy = deepcopy(_json(POLICY_PATH))
    lock = deepcopy(_json(SOURCE_LOCK_PATH))
    asset = lock["sources"][0]["assets"][0]
    if mutation == "native-version":
        asset["nativeVersion"] = "changed"
    elif mutation == "archive-sha":
        asset["sha256"] = "0" * 64
    else:
        asset["members"][0]["sha256"] = "0" * 64
    lock_path = tmp_path / SOURCE_LOCK_PATH.name
    _write_json(lock_path, lock)
    policy["sourceLock"]["sha256"] = sha256_file(lock_path)
    policy_path = tmp_path / POLICY_PATH.name
    _write_json(policy_path, policy)

    with pytest.raises(CoastlineContractError):
        validate_coastline_sources(lock_path, load_coastline_policy(policy_path))
