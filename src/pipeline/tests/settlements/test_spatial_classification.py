"""Deterministic, fixture-only settlement spatial-classification boundary."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pyproj
import pytest
import shapely
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform

from searise_pipeline.settlements.alternate_names import NameVariant
from searise_pipeline.settlements.catalogue import CataloguePlace
from searise_pipeline.settlements.geonames import Lineage
from searise_pipeline.settlements.spatial_classification import (
    CORE_CAPITAL_FEATURE_CODES,
    SPATIAL_FIXTURE_SHA256,
    ProductionSpatialBlocker,
    SpatialClassificationError,
    SpatialResultRow,
    classification_sql,
    classify_spatial_rows,
    load_fixture_geometry_bindings,
    production_geometry_bindings,
)
from searise_pipeline.settlements.spatial_toolchain import (
    SpatialToolchainEvidence,
    current_spatial_platform,
    load_spatial_manifest,
    verify_spatial_toolchain,
)

ROOT = Path(__file__).parents[4]
FIXTURE = ROOT / "src/pipeline/tests/settlements/fixtures/spatial/fixture-manifest.json"
TOOLCHAIN = ROOT / "src/pipeline/toolchain/duckdb-spatial-extensions.json"


def _fixture():
    raw = json.loads(FIXTURE.read_text())
    cases = tuple(
        SimpleNamespace(
            case_id=value["caseId"],
            source_line=value["sourceLine"],
            place_id=value["placeId"],
            name=value["name"],
            latitude=value["latitude"],
            longitude=value["longitude"],
            population=value["population"],
            support_covers=value["supportCovers"],
            coastal_covers=value["coastalCovers"],
            distance_to_shoreline_meters=value["distanceToShorelineMeters"],
        )
        for value in raw["cases"]
    )
    references = tuple(
        SimpleNamespace(
            path=value["path"], sha256=value["sha256"], ids=tuple(value["sourceRecordIds"])
        )
        for value in raw["normalizationFixtureReferences"]
    )
    return SimpleNamespace(
        manifest_sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        data_provenance_class=raw["dataProvenanceClass"],
        owner_approval_claim=raw["ownerApprovalClaim"],
        geometry=load_fixture_geometry_bindings(FIXTURE, repository_root=ROOT),
        toolchain_manifest_sha256=raw["toolchain"]["manifestSha256"],
        production_blocker=raw["productionBlocker"]["reason"],
        normalization_references=references,
        distance_oracle=raw["distanceOracle"],
        cases=cases,
    )


def _evidence() -> SpatialToolchainEvidence:
    pin = load_spatial_manifest(TOOLCHAIN).platforms["linux-x86_64"]
    return SpatialToolchainEvidence(
        platform="linux-x86_64",
        duckdb_version="1.5.4",
        extension_path=pin.extension.relative_path,
        extension_sha256=pin.extension.sha256,
        smoke_point=(12.5, 41.9),
        smoke_distance=5.0,
    )


def _place(case) -> CataloguePlace:
    source_id = int(case.place_id.removeprefix("geonames:"))
    lineage = Lineage(
        "synthetic-spatial-cases",
        "fixture-manifest.json#cases",
        "synthetic-v1",
        case.source_line,
        source_id,
        SPATIAL_FIXTURE_SHA256,
    )
    return CataloguePlace(
        id=case.place_id,
        source_spelling=case.name,
        canonical_name=NameVariant(case.name, None, "Latn"),
        ascii_name=case.name,
        alternate_names=(),
        country_code="XX",
        admin1_code=None,
        admin1_name=None,
        latitude=case.latitude,
        longitude=case.longitude,
        population=case.population,
        feature_code="PPL",
        source_updated_at=date(2026, 8, 10),
        lineage=(lineage,),
    )


def _row(case) -> SpatialResultRow:
    return SpatialResultRow(
        case.place_id,
        case.support_covers,
        case.coastal_covers,
        case.distance_to_shoreline_meters,
    )


def _classify(*, places=None, rows=None, fixture=None, evidence=None, geometry=None):
    fixture = fixture or _fixture()
    return classify_spatial_rows(
        places if places is not None else [_place(case) for case in fixture.cases],
        rows if rows is not None else [_row(case) for case in fixture.cases],
        geometry=geometry or fixture.geometry,
        toolchain_evidence=evidence or _evidence(),
        toolchain_manifest_path=TOOLCHAIN,
    )


def test_fixture_binds_three_distinct_geometries_toolchain_and_name_evidence() -> None:
    fixture = _fixture()

    assert fixture.manifest_sha256 == SPATIAL_FIXTURE_SHA256
    assert fixture.data_provenance_class == "synthetic-fixture"
    assert fixture.geometry.geometry_status == "selected-scope-approximation"
    assert fixture.geometry.publication_eligible is False
    assert fixture.owner_approval_claim is False
    assert CORE_CAPITAL_FEATURE_CODES == {"PPLC", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5"}
    assert [item.role for item in fixture.geometry.items] == ["support", "coastal", "shoreline"]
    assert len({item.sha256 for item in fixture.geometry.items}) == 3
    assert len({item.path for item in fixture.geometry.items}) == 3
    assert fixture.toolchain_manifest_sha256 == (
        "77c7ea3422e67be2f8d23f0dcef2d5d36236f01b8856f76289ed1e0532359ca6"
    )
    assert {record_id for ref in fixture.normalization_references for record_id in ref.ids} == {
        3039322,
        3128760,
    }
    for reference in fixture.normalization_references:
        assert hashlib.sha256((ROOT / reference.path).read_bytes()).hexdigest() == reference.sha256
    for case in fixture.cases:
        lineage = _place(case).lineage[0]
        assert (lineage.asset_id, lineage.source_file, lineage.source_release) == (
            "synthetic-spatial-cases",
            "fixture-manifest.json#cases",
            "synthetic-v1",
        )
        assert (lineage.source_line, lineage.source_record_id, lineage.source_sha256) == (
            case.source_line,
            int(case.place_id.removeprefix("geonames:")),
            SPATIAL_FIXTURE_SHA256,
        )
    assert fixture.production_blocker == "shoreline-geometry-unavailable"


def test_sql_uses_covers_and_a_separate_shoreline_distance_not_boundaries() -> None:
    sql = classification_sql()

    assert sql.count("ST_Covers(") == 2
    assert sql.count("ST_Transform(") == 2
    assert sql.count("'EPSG:4326', 'EPSG:3035', true") == 2
    assert "CAST(ST_Distance(metric_point, metric_shoreline) AS BIGINT)" in sql
    assert "ST_Distance_Spheroid" not in sql
    assert "ST_Contains" not in sql
    assert "ST_Envelope" not in sql
    assert "ST_Boundary" not in sql


def test_expected_fixture_distances_use_an_independent_pinned_metric_oracle() -> None:
    fixture = _fixture()
    assert fixture.distance_oracle == {
        "library": "pyproj.Transformer+shapely.distance",
        "pyprojVersion": "3.6.1",
        "projVersion": "9.3.0",
        "shapelyVersion": "2.0.7",
        "sourceCrs": "EPSG:4326",
        "metricCrs": "EPSG:3035",
        "areaOfUseBoundsWgs84": [-35.58, 24.6, 44.83, 84.73],
        "alwaysXY": True,
        "operation": "transform-point-and-shoreline-then-planar-distance",
        "distanceMethodVersion": "epsg3035-planar-whole-meter-half-even-v1",
        "quantization": "DuckDB DOUBLE-to-BIGINT nearest-half-to-even",
    }
    assert (pyproj.__version__, pyproj.proj_version_str, shapely.__version__) == (
        "3.6.1",
        "9.3.0",
        "2.0.7",
    )
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    assert (
        list(pyproj.CRS.from_epsg(3035).area_of_use.bounds)
        == fixture.distance_oracle["areaOfUseBoundsWgs84"]
    )
    west, south, east, north = fixture.distance_oracle["areaOfUseBoundsWgs84"]
    fixture_geometries = {}
    for binding in fixture.geometry.items:
        raw = json.loads((ROOT / binding.path).read_text())["features"][0]["geometry"]
        fixture_geometries[binding.role] = shape(raw)
        min_x, min_y, max_x, max_y = fixture_geometries[binding.role].bounds
        assert west <= min_x <= max_x <= east and south <= min_y <= max_y <= north
    shoreline = transform(transformer.transform, fixture_geometries["shoreline"])
    for case in fixture.cases:
        assert west <= case.longitude <= east and south <= case.latitude <= north
        point = transform(transformer.transform, Point(case.longitude, case.latitude))
        assert round(point.distance(shoreline)) == case.distance_to_shoreline_meters


def test_live_pinned_duckdb_spatial_classification_matches_oracle() -> None:
    cache_value = os.getenv("SEARISE_SPATIAL_CACHE_ROOT")
    if not cache_value:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail("CI did not export SEARISE_SPATIAL_CACHE_ROOT")
        pytest.skip("exact pinned DuckDB Spatial cache is unavailable locally")

    import duckdb

    cache_root = Path(cache_value)
    manifest = load_spatial_manifest(TOOLCHAIN)
    platform = current_spatial_platform()
    verify_spatial_toolchain(cache_root, manifest, platform_key=platform)
    extension = cache_root / manifest.platforms[platform].extension.relative_path
    fixture = _fixture()
    connection = duckdb.connect()
    try:
        connection.execute(f"LOAD '{extension.as_posix().replace(chr(39), chr(39) * 2)}'")
        connection.execute(
            "CREATE TEMP TABLE spatial_place_input "
            "(place_id VARCHAR, latitude DOUBLE, longitude DOUBLE)"
        )
        connection.execute(
            "CREATE TEMP TABLE spatial_geometry_input (role VARCHAR, geometry GEOMETRY)"
        )
        connection.executemany(
            "INSERT INTO spatial_place_input VALUES (?, ?, ?)",
            [(case.place_id, case.latitude, case.longitude) for case in fixture.cases],
        )
        for binding in fixture.geometry.items:
            raw = json.loads((ROOT / binding.path).read_text())["features"][0]["geometry"]
            connection.execute(
                "INSERT INTO spatial_geometry_input SELECT ?, ST_GeomFromGeoJSON(?)",
                [binding.role, json.dumps(raw, separators=(",", ":"))],
            )
        rows = connection.execute(classification_sql()).fetchall()
        ties = connection.execute(
            "SELECT CAST(? AS BIGINT), CAST(? AS BIGINT), CAST(? AS BIGINT)",
            [0.5, 1.5, 2.5],
        ).fetchone()
    finally:
        connection.close()

    expected = sorted(fixture.cases, key=lambda case: int(case.place_id.removeprefix("geonames:")))
    assert [row[:3] for row in rows] == [
        (case.place_id, case.support_covers, case.coastal_covers) for case in expected
    ]
    assert ties == (0, 2, 2)
    assert [row[3] for row in rows] == [case.distance_to_shoreline_meters for case in expected]


def test_named_cases_are_ordered_with_stable_membership_and_outside_ledger() -> None:
    fixture = _fixture()
    assert {case.case_id for case in fixture.cases} == {
        "inland-city",
        "coastal-village",
        "support-boundary",
        "island-harbor",
        "excluded-transcontinental",
        "zero-population",
    }

    result = _classify(
        places=list(reversed([_place(case) for case in fixture.cases])),
        rows=list(reversed([_row(case) for case in fixture.cases])),
        fixture=fixture,
    )

    assert [item.place.id for item in result.places] == [
        "geonames:900000101",
        "geonames:900000102",
        "geonames:900000103",
        "geonames:900000104",
        "geonames:900000106",
    ]
    by_name = {item.place.source_spelling: item for item in result.places}
    assert by_name["Inland City"].catalog_membership == ("europe-core",)
    assert by_name["Coastal Village"].catalog_membership == ("europe-coastal",)
    assert by_name["Boundary Place"].catalog_membership == ()
    assert by_name["Island Harbor"].distance_to_shoreline_meters == 0
    assert type(by_name["Island Harbor"].distance_to_shoreline_meters) is int
    assert by_name["Zero Population Hamlet"].place.population == 0
    assert by_name["Zero Population Hamlet"].catalog_membership == ()
    assert [(item.place_id, item.reason) for item in result.rejections] == [
        ("geonames:900000105", "outside-support")
    ]


@pytest.mark.parametrize("population", (0, None))
@pytest.mark.parametrize("feature_code", ("PPLC", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5"))
def test_populationless_capitals_are_core_audit_records(feature_code: str, population) -> None:
    case = next(case for case in _fixture().cases if case.case_id == "zero-population")
    result = _classify(
        places=[replace(_place(case), feature_code=feature_code, population=population)],
        rows=[_row(case)],
    )

    assert result.places[0].catalog_membership == ("europe-core",)


def test_null_population_non_capitals_remain_accepted_and_coastal_is_independent() -> None:
    fixture = _fixture()
    inland, coastal = (
        next(case for case in fixture.cases if case.case_id == name)
        for name in (
            "zero-population",
            "coastal-village",
        )
    )
    result = _classify(
        places=[replace(_place(case), population=None) for case in (inland, coastal)],
        rows=[_row(case) for case in (inland, coastal)],
    )

    assert [place.catalog_membership for place in result.places] == [
        ("europe-coastal",),
        (),
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("support_covers", None),
        ("support_covers", 1),
        ("coastal_covers", None),
        ("distance_to_shoreline_meters", None),
        ("distance_to_shoreline_meters", 1.0),
        ("distance_to_shoreline_meters", -1.0),
        ("distance_to_shoreline_meters", float("nan")),
        ("distance_to_shoreline_meters", float("inf")),
    ],
)
def test_null_or_invalid_spatial_results_fail_closed(field: str, value: object) -> None:
    fixture = _fixture()
    rows = [_row(case) for case in fixture.cases]
    rows[0] = replace(rows[0], **{field: value})

    with pytest.raises(SpatialClassificationError, match="invalid spatial result"):
        _classify(rows=rows, fixture=fixture)


def test_coastal_result_cannot_escape_support() -> None:
    fixture = _fixture()
    rows = [_row(case) for case in fixture.cases]
    outside = next(index for index, case in enumerate(fixture.cases) if not case.support_covers)
    rows[outside] = replace(rows[outside], coastal_covers=True)

    with pytest.raises(SpatialClassificationError, match="coastal coverage exceeds support"):
        _classify(rows=rows, fixture=fixture)


def test_duplicate_missing_or_orphan_place_id_fails_the_whole_run() -> None:
    fixture = _fixture()
    places = [_place(case) for case in fixture.cases]
    rows = [_row(case) for case in fixture.cases]

    with pytest.raises(SpatialClassificationError, match="duplicate catalog place id"):
        _classify(places=[*places, places[0]], rows=rows, fixture=fixture)
    with pytest.raises(SpatialClassificationError, match="missing spatial result"):
        _classify(places=places, rows=rows[:-1], fixture=fixture)
    with pytest.raises(SpatialClassificationError, match="orphan spatial result"):
        _classify(places=places[:-1], rows=rows, fixture=fixture)
    with pytest.raises(SpatialClassificationError, match="duplicate spatial result"):
        _classify(places=places, rows=[*rows, rows[0]], fixture=fixture)
    with pytest.raises(SpatialClassificationError, match="invalid catalog place id"):
        _classify(places=[replace(places[0], id="missing")], rows=[rows[0]], fixture=fixture)


@pytest.mark.parametrize("field", ("version", "sha256", "predicate"))
def test_geometry_identity_mutation_fails_closed(field: str) -> None:
    fixture = _fixture()
    support = replace(fixture.geometry.support, **{field: "0" * 64})
    geometry = replace(fixture.geometry, support=support)

    with pytest.raises(SpatialClassificationError, match="geometry binding"):
        _classify(fixture=fixture, geometry=geometry)


def test_status_publication_and_boundary_substitution_fail_closed() -> None:
    fixture = _fixture()
    with pytest.raises(SpatialClassificationError, match="selected-scope-approximation"):
        _classify(
            fixture=fixture,
            geometry=replace(fixture.geometry, geometry_status="reviewed"),
        )
    with pytest.raises(SpatialClassificationError, match="publication eligible"):
        _classify(
            fixture=fixture,
            geometry=replace(fixture.geometry, publication_eligible=True),
        )
    substituted = replace(
        fixture.geometry.shoreline,
        path=fixture.geometry.coastal.path,
        sha256=fixture.geometry.coastal.sha256,
    )
    with pytest.raises(SpatialClassificationError, match="shoreline must be separately identified"):
        _classify(
            fixture=fixture,
            geometry=replace(fixture.geometry, shoreline=substituted),
        )


def test_toolchain_identity_mismatch_fails_before_classification() -> None:
    evidence = replace(_evidence(), duckdb_version="1.5.3")
    with pytest.raises(SpatialClassificationError, match="toolchain evidence"):
        _classify(evidence=evidence)


def test_production_build_is_explicitly_blocked_without_real_shoreline() -> None:
    with pytest.raises(ProductionSpatialBlocker, match="shoreline-geometry-unavailable"):
        production_geometry_bindings(ROOT)
