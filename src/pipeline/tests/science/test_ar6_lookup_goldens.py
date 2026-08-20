"""Validate offline AR6 goldens and optionally replay them against source bytes."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import geopandas as gpd  # type: ignore[import-untyped]
import numpy as np
import pytest
import rasterio
from jsonschema import Draft202012Validator, FormatChecker
from shapely.geometry import Point

from searise_pipeline.science import (
    Ar6GridSlice,
    Ar6ProjectionInterval,
    extract_projection_interval,
    load_science_contracts,
    lookup_ar6_projection,
    open_verified_ar6_member,
    verify_ar6_archive,
)

REPO_ROOT = Path(__file__).parents[4]
SCIENCE_DIR = REPO_ROOT / "src/pipeline/science"
EVIDENCE_DIR = SCIENCE_DIR / "evidence"
SOURCE_LOCK_PATH = REPO_ROOT / "src/pipeline/sources/source-lock.json"
OUTCOME_PARITY_PATH = EVIDENCE_DIR / "ar6-four-outcome-parity-v1.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _goldens() -> dict[str, Any]:
    return _load(EVIDENCE_DIR / "ar6-lookup-goldens.json")


def _outcome_parity_fixture() -> dict[str, Any]:
    return _load(OUTCOME_PARITY_PATH)


def _fixture_cog_interval(
    fixture: dict[str, Any],
) -> tuple[Ar6ProjectionInterval, np.ndarray[Any, Any], Path]:
    manifest = _load(REPO_ROOT / fixture["release"]["manifestPath"])
    selection = fixture["selection"]
    artifact = next(
        item
        for item in manifest["artifacts"]
        if item["role"] == "projection-analysis-cog"
        and item["projectionContext"]["scenario"] == selection["scenario"]
        and item["projectionContext"]["horizon"] == selection["horizon"]
    )
    context = artifact["projectionContext"]
    assert context["values"]["quantiles"] == fixture["contract"]["requiredQuantiles"]
    assert context["grid"]["nativeResolutionDegrees"] == 1
    release_id = fixture["release"]["dataReleaseId"]
    payload_root = REPO_ROOT / "contracts/release/v1/fixtures/release" / release_id
    cog_path = payload_root / artifact["path"]
    source_grid_path = (
        REPO_ROOT
        / "contracts/release/v2/fixtures/browser-release"
        / release_id
        / "analysis/source-grid.json.gz"
    )

    with rasterio.open(cog_path) as dataset:
        raw = dataset.read()
        nodata = dataset.nodata
        assert nodata == context["grid"]["nodata"]
        latitudes = np.asarray([dataset.xy(row, 0)[1] for row in range(dataset.height)])
        longitudes = np.asarray([dataset.xy(0, column)[0] for column in range(dataset.width)])
    with gzip.open(source_grid_path, "rt", encoding="utf-8") as stream:
        source_grid = json.load(stream)
    location_ids = np.flipud(
        np.asarray(source_grid["locationIds"], dtype=np.int64).reshape(
            source_grid["height"], source_grid["width"]
        )
    )
    values_m = np.where(raw == nodata, np.nan, raw * context["values"]["scaleToMetres"])

    def grid(band: int) -> Ar6GridSlice:
        return Ar6GridSlice(
            latitudes=latitudes,
            longitudes=longitudes,
            location_ids=location_ids,
            values_m=values_m[band],
        )

    interval = Ar6ProjectionInterval(
        scenario=selection["scenario"],
        horizon=selection["horizon"],
        baseline=context["values"]["baseline"],
        source_release=context["source"]["sourceRelease"],
        member_sha256=context["source"]["memberSha256"],
        lower=grid(0),
        central=grid(1),
        upper=grid(2),
    )
    return interval, raw, cog_path


def test_offline_goldens_match_schema_and_all_file_bindings() -> None:
    goldens = _goldens()
    schema = _load(EVIDENCE_DIR / "ar6-lookup-goldens.schema.json")

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(goldens)
    bindings = [
        goldens["validationContract"],
        goldens["decisionContract"],
        goldens["scopeGeometry"]["support"],
        goldens["scopeGeometry"]["coastal"],
        {
            "path": goldens["provenance"]["generatorPath"],
            "sha256": goldens["provenance"]["generatorSha256"],
        },
    ]
    for binding in bindings:
        assert _sha256(REPO_ROOT / binding["path"]) == binding["sha256"]


def test_offline_goldens_bind_every_locked_member_and_projection_value() -> None:
    goldens = _goldens()
    validation = _load(SCIENCE_DIR / "ar6-lookup-validation.json")
    source_lock = _load(SOURCE_LOCK_PATH)
    source = next(
        item
        for item in source_lock["sources"]
        if item["id"] == validation["source"]["sourceId"]
        and item["version"] == validation["source"]["version"]
    )
    archive = next(
        item for item in source["assets"] if item["sha256"] == validation["source"]["archiveSha256"]
    )
    assert goldens["provenance"]["archiveSha256"] == archive["sha256"]
    assert goldens["provenance"]["memberSha256"] == {
        member["scenario"]: member["sha256"] for member in archive["members"]
    }

    available = [item for item in goldens["results"] if item["state"] == "ProjectionAvailable"]
    assert len(available) == 7
    for item in available:
        combinations = {
            (projection["scenario"], projection["horizon"]) for projection in item["projections"]
        }
        assert combinations == {
            (scenario, horizon)
            for scenario in ("ssp1-26", "ssp2-45", "ssp5-85")
            for horizon in (2030, 2050, 2100)
        }
        for projection in item["projections"]:
            assert projection["lowerMillimetres"] <= projection["centralMillimetres"]
            assert projection["centralMillimetres"] <= projection["upperMillimetres"]
            for statistic in ("lower", "central", "upper"):
                assert projection[f"{statistic}Metres"] == pytest.approx(
                    projection[f"{statistic}Millimetres"] * 0.001,
                    abs=goldens["numericToleranceMetres"],
                )


def test_real_nodata_search_exhausts_the_declared_product_scope() -> None:
    evidence = _goldens()["nodataSearchEvidence"]

    assert evidence == {
        "searchRule": (
            "all native grid locations covered by the versioned Europe support and coastal "
            "scope across all required scenarios, horizons, and quantiles"
        ),
        "inScopeGridLocationCount": 154,
        "scenarioLocationChecks": 462,
        "sourceNodataLocationCount": 0,
        "conclusion": "no-real-in-scope-source-nodata-location-exists",
        "syntheticControlId": "nearest-location-is-nodata",
    }


def test_committed_browser_fixture_matches_all_four_adr024_outcomes() -> None:
    fixture = _outcome_parity_fixture()
    contract = fixture["contract"]
    expected_states = {
        "ProjectionAvailable",
        "DataUnavailable",
        "OutOfScope",
        "UnsupportedGeography",
    }
    assert fixture["fixtureRole"] == "authoritative-adr-024-behavior-golden"
    assert fixture["dataProvenanceClass"] == "synthetic-fixture"
    assert contract == {
        "resultStates": [
            "ProjectionAvailable",
            "DataUnavailable",
            "OutOfScope",
            "UnsupportedGeography",
        ],
        "requiredQuantiles": [0.167, 0.5, 0.833],
        "locationSelection": "nearest-source-grid-location",
        "maximumDistanceKilometres": 100,
        "distanceLimitInclusive": True,
        "prohibitedOperations": [
            "interpolation",
            "terrain-comparison",
            "binary-exposure-classification",
            "pmtiles-as-science",
        ],
    }

    interval, raw_cog, cog_path = _fixture_cog_interval(fixture)
    manifest = _load(REPO_ROOT / fixture["release"]["manifestPath"])
    overlay_root = (
        REPO_ROOT
        / "contracts/release/v2/fixtures/browser-release"
        / fixture["release"]["dataReleaseId"]
    )
    support = gpd.read_parquet(
        overlay_root
        / next(item["path"] for item in manifest["artifacts"] if item["role"] == "support-boundary")
    ).geometry.iloc[0]
    coastal = gpd.read_parquet(
        overlay_root
        / next(item["path"] for item in manifest["artifacts"] if item["role"] == "coastal-boundary")
    ).geometry.iloc[0]
    lookup_contract = _load(SCIENCE_DIR / "ar6-lookup-validation.json")
    actual_states: set[str] = set()
    for case in fixture["cases"]:
        coordinates = case["coordinates"]
        point = Point(coordinates["longitude"], coordinates["latitude"])
        classification = (
            "OutsideEurope"
            if not support.covers(point)
            else (
                "InEuropeAndCoastalZone"
                if coastal.covers(point)
                else "InEuropeOutsideCoastalZone"
            )
        )
        assert classification == case["geographyClassification"]
        actual = lookup_ar6_projection(
            interval,
            latitude=coordinates["latitude"],
            longitude=coordinates["longitude"],
            support=support,
            coastal_scope=coastal,
            lookup_contract=lookup_contract,
        )
        expected = case["expected"]
        actual_states.add(actual.state)
        assert (actual.state, actual.reason_code) == (
            expected["resultState"],
            expected["reason"],
        )
        if source := expected.get("source"):
            assert actual.source is not None
            assert {
                "locationId": actual.source.location_id,
                "latitude": actual.source.latitude,
                "longitude": actual.source.longitude,
                "distanceKilometres": actual.source.distance_km,
            } == source
        else:
            assert actual.source is None
        if projection := expected.get("projectionMillimetres"):
            assert [
                round(value * 1000)
                for value in (
                    actual.lower_m,
                    actual.central_m,
                    actual.upper_m,
                )
                if value is not None
            ] == [
                projection["lower"],
                projection["median"],
                projection["upper"],
            ]
        if nodata := case.get("nodataEvidence"):
            assert nodata["kind"] == "committed-nine-cog-cell-and-browser-boundary-control"
            selected_path = nodata["artifactPathPattern"].format(**fixture["selection"])
            assert REPO_ROOT / selected_path == cog_path
            assert raw_cog[:, nodata["row"], nodata["column"]].tolist() == nodata[
                "bandValuesForEveryCombination"
            ]
            assert nodata["storedNodata"] == -32768
            assert actual.central_m is None

    assert actual_states == expected_states


@pytest.mark.skipif(
    not os.environ.get("SEARISE_AR6_ARCHIVE"),
    reason="set SEARISE_AR6_ARCHIVE to replay goldens against the 9.24 GB source archive",
)
def test_xarray_reader_and_lookup_match_independent_netcdf4_goldens() -> None:
    archive_path = Path(os.environ["SEARISE_AR6_ARCHIVE"])
    source_lock = _load(SOURCE_LOCK_PATH)
    contracts = load_science_contracts(SCIENCE_DIR)
    projection = contracts.source_semantics["projection"]
    lookup_contract = contracts.lookup_validation
    assert lookup_contract is not None
    goldens = _goldens()
    expected_by_id = {item["id"]: item for item in goldens["results"]}
    support = gpd.read_file(REPO_ROOT / "data/geometry/europe.geojson").geometry.union_all()
    coastal = gpd.read_file(
        REPO_ROOT / "data/geometry/coastal_analysis_zone.geojson"
    ).geometry.union_all()
    verified = verify_ar6_archive(archive_path, source_lock, projection)

    for scenario in ("ssp1-26", "ssp2-45", "ssp5-85"):
        with open_verified_ar6_member(verified, scenario) as (dataset, identity):
            for horizon in (2030, 2050, 2100):
                interval = extract_projection_interval(
                    dataset,
                    projection,
                    scenario,
                    horizon,
                    member_identity=identity,
                    verified_member_sha256=identity.sha256,
                )
                for declared in lookup_contract["validation"]["goldenPoints"]:
                    expected = expected_by_id[declared["id"]]
                    coordinates = declared["coordinates"]
                    actual = lookup_ar6_projection(
                        interval,
                        latitude=coordinates["latitude"],
                        longitude=coordinates["longitude"],
                        support=support,
                        coastal_scope=coastal,
                        lookup_contract=lookup_contract,
                    )
                    assert (actual.state, actual.reason_code) == (
                        expected["state"],
                        expected["reasonCode"],
                    )
                    if expected["state"] != "ProjectionAvailable":
                        assert actual.source is None
                        continue
                    expected_projection = next(
                        item
                        for item in expected["projections"]
                        if item["scenario"] == scenario and item["horizon"] == horizon
                    )
                    assert actual.source is not None
                    assert {
                        "locationId": actual.source.location_id,
                        "latitude": actual.source.latitude,
                        "longitude": actual.source.longitude,
                        "family": actual.source.family,
                        "distanceKilometres": actual.source.distance_km,
                    } == expected["source"]
                    assert actual.member_sha256 == identity.sha256
                    for statistic in ("lower", "central", "upper"):
                        actual_metres = getattr(actual, f"{statistic}_m")
                        assert actual_metres == pytest.approx(
                            expected_projection[f"{statistic}Metres"],
                            abs=goldens["numericToleranceMetres"],
                        )
                        assert (
                            round(actual_metres * 1000)
                            == expected_projection[f"{statistic}Millimetres"]
                        )
