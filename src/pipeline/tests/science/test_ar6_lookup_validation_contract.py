"""Tests that freeze the AR6 lookup validation set before reference extraction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
from jsonschema import Draft202012Validator
from shapely.geometry import Point  # type: ignore[import-untyped]

SCIENCE_DIR = Path(__file__).parents[2] / "science"


def _document(name: str) -> dict[str, object]:
    return json.loads((SCIENCE_DIR / name).read_text(encoding="utf-8"))


def test_lookup_validation_contract_matches_schema() -> None:
    contract = _document("ar6-lookup-validation.json")
    schema = _document("ar6-lookup-validation.schema.json")

    Draft202012Validator(schema).validate(contract)


def test_member_hashes_are_bound_to_source_lock() -> None:
    contract = _document("ar6-lookup-validation.json")
    source_lock = json.loads(
        (SCIENCE_DIR.parent / "sources/source-lock.json").read_text(encoding="utf-8")
    )
    source = next(
        item
        for item in source_lock["sources"]
        if item["id"] == contract["source"]["sourceId"]
        and item["version"] == contract["source"]["version"]
    )
    archive = next(
        item
        for item in source["assets"]
        if item["sha256"] == contract["source"]["archiveSha256"]
    )
    upstream_to_product = {
        "ssp126": "ssp1-26",
        "ssp245": "ssp2-45",
        "ssp585": "ssp5-85",
    }
    locked = {
        upstream_to_product[member["scenario"]]: member["sha256"]
        for member in archive["members"]
    }

    assert contract["source"]["memberSha256ByScenario"] == locked


def test_golden_set_and_tolerance_are_predeclared() -> None:
    contract = _document("ar6-lookup-validation.json")
    validation = contract["validation"]

    assert validation["numericToleranceMetres"] == 1e-6
    assert validation["scenarioHorizonMatrix"] == {
        "scenarios": ["ssp1-26", "ssp2-45", "ssp5-85"],
        "horizons": [2030, 2050, 2100],
    }
    points = validation["goldenPoints"]
    assert len({point["id"] for point in points}) == len(points)
    coverage = {point["coverage"] for point in points}
    assert {
        "Atlantic and North Sea",
        "Baltic Sea",
        "Mediterranean and Adriatic Sea",
        "Black Sea",
    }.issubset(coverage)
    kinds = {point["kind"] for point in points}
    assert {"port", "estuary", "island", "high-latitude", "scope-control"} <= kinds


def test_algorithmic_controls_freeze_fail_closed_edges() -> None:
    contract = _document("ar6-lookup-validation.json")
    controls = {
        item["purpose"]: (item["expectedState"], item["expectedReasonCode"])
        for item in contract["validation"]["algorithmicControls"]
    }

    assert controls == {
        "nodata": ("DataUnavailable", "source-value-nodata"),
        "distance-boundary": ("ProjectionAvailable", "projection-available"),
        "beyond-maximum-distance": (
            "DataUnavailable",
            "source-location-too-distant",
        ),
        "tie-break": ("ProjectionAvailable", "projection-available"),
    }


def test_lookup_is_grid_only_and_never_skips_nodata() -> None:
    lookup = _document("ar6-lookup-validation.json")["lookup"]

    assert lookup == {
        "sourceFamily": "native-one-degree-grid",
        "locationSelection": "nearest-source-grid-location",
        "maximumDistanceKm": 100,
        "distance": {
            "algorithm": "haversine",
            "earthMeanRadiusKm": 6371.0088,
            "boundary": "inclusive",
            "reportedDistanceDecimalPlaces": 6,
        },
        "tieBreak": "lowest-source-location-id",
        "requiredQuantiles": [0.167, 0.5, 0.833],
        "nodataRule": (
            "resolve-nearest-location-first-then-fail-if-any-required-quantile-is-fill"
        ),
        "interpolation": "forbidden",
        "extrapolation": "forbidden",
    }


def test_file_bindings_match_exact_decision_and_source_contracts() -> None:
    contract = _document("ar6-lookup-validation.json")
    repo_root = SCIENCE_DIR.parents[2]
    bindings = [
        contract["source"]["sourceSemanticsBinding"],
        contract["source"]["sourceLockBinding"],
        contract["source"]["decisionContract"],
    ]

    for binding in bindings:
        contents = (repo_root / binding["path"]).read_bytes()
        assert hashlib.sha256(contents).hexdigest() == binding["sha256"]


def test_lookup_parameters_match_the_accepted_projection_decision() -> None:
    validation = _document("ar6-lookup-validation.json")
    decision = _document("ar6-projection-contract.json")
    lookup = validation["lookup"]
    accepted = decision["spatialLookup"]["point"]

    assert lookup["locationSelection"] == accepted["operator"]
    assert lookup["maximumDistanceKm"] == accepted["maximumDistanceKilometres"]
    assert lookup["distance"]["algorithm"] == accepted["distanceMetric"]
    assert lookup["distance"]["earthMeanRadiusKm"] == accepted["earthRadiusKilometres"]
    assert (
        lookup["distance"]["reportedDistanceDecimalPlaces"]
        == accepted["reportedDistanceDecimalPlaces"]
    )
    assert lookup["tieBreak"] == accepted["tieBreak"]
    assert accepted["interpolation"] == "none"
    assert accepted["tideGaugeFallback"] == "prohibited"
    assert accepted["nodataSubstitution"] == "prohibited"
    assert (
        validation["resultContract"]["stableReasonCodes"][
            "sourceGridBeyondMaximumDistance"
        ]
        in decision["resultContract"]["dataUnavailableReasons"]
    )
    assert (
        validation["validation"]["numericToleranceMetres"]
        == decision["validation"]["absoluteToleranceMetres"]
    )


def test_golden_scope_states_match_the_versioned_geometries() -> None:
    repo_root = SCIENCE_DIR.parents[2]
    contract = _document("ar6-lookup-validation.json")
    support = gpd.read_file(repo_root / "data/geometry/europe.geojson").geometry.union_all()
    coastal = gpd.read_file(
        repo_root / "data/geometry/coastal_analysis_zone.geojson"
    ).geometry.union_all()

    for golden in contract["validation"]["goldenPoints"]:
        coordinates = golden["coordinates"]
        point = Point(coordinates["longitude"], coordinates["latitude"])
        observed = "ProjectionAvailable"
        if not support.covers(point):
            observed = "UnsupportedGeography"
        elif not coastal.covers(point):
            observed = "OutOfScope"
        assert observed == golden["expectedState"], golden["id"]
